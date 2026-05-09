"""
Script automático para revisar mails de gastos y actualizar gastos.json.
Se puede ejecutar manualmente o via tarea programada de Windows.

Uso: python check_mails.py

Lee config.json para saber qué remitentes buscar, conecta a Gmail via IMAP,
extrae montos y vencimientos, y actualiza gastos.json directamente.
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import imaplib
import email
from email.header import decode_header
import json
import re
import os
import shutil
import tempfile
from datetime import datetime, timedelta

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GASTOS_FILE = os.path.join(BASE_DIR, "gastos.json")
CONFIG_FILE = os.path.join(BASE_DIR, "config.json")
LOG_FILE = os.path.join(BASE_DIR, "check_mails_log.json")

# ── CONFIG ──
GMAIL_USER = "tominorman@gmail.com"
GMAIL_PASS = "wjpj bolj qbvl wykd"
PDF_PASSWORD = "29834279"
DIAS_ATRAS = 7  # Cuántos días hacia atrás buscar

# Mapeo de remitente a gasto_id
REMITENTE_MAP = {
    "estudio.ormachea@gmail.com": ["ormachea", "autonomos"],
    "diegoormachea@hotmail.com": ["ormachea"],
    "asociados@bancocredicoop.coop": ["cabal_credicoop", "visa_credicoop"],
    "mensajesyalertas@bancocredicoop.coop": ["cabal_credicoop", "visa_credicoop"],
    "noreply@eresumen.com": ["visa_nbsf"],
    "info@eresumen.com": ["visa_nbsf"],
    "noreply@consorcioabierto.com": ["ubajay"],
    "oficinavirtual@epe.santafe.gov.ar": ["epe"],
    "banco@bancojulio.com.ar": [],
}

# ── HELPERS ──

def decodificar_header(h):
    if not h:
        return ""
    partes = decode_header(h)
    resultado = []
    for parte, enc in partes:
        if isinstance(parte, bytes):
            resultado.append(parte.decode(enc or "utf-8", errors="replace"))
        else:
            resultado.append(parte)
    return " ".join(resultado)

def extraer_texto(msg):
    texto = ""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                try:
                    texto += part.get_payload(decode=True).decode("utf-8", errors="replace")
                except:
                    pass
            elif ct == "text/html" and "attachment" not in cd and not texto:
                try:
                    html = part.get_payload(decode=True).decode("utf-8", errors="replace")
                    # Strip HTML tags para extraer texto útil
                    texto += re.sub(r'<[^>]+>', ' ', html)
                except:
                    pass
    else:
        try:
            texto = msg.get_payload(decode=True).decode("utf-8", errors="replace")
        except:
            pass
    return texto[:5000]  # Limitar para no gastar memoria

def parse_monto_ars(texto):
    """Extrae montos en ARS del texto. Busca patrones como $123.456,78 o $123456."""
    montos = []

    # Patrón 1: $ seguido de números con separadores argentinos ($123.456,78)
    patron1 = re.findall(r'\$\s*([\d.]+(?:,\d{2})?)', texto)
    for m in patron1:
        try:
            # "123.456,78" → 123456.78
            val = m.replace('.', '').replace(',', '.')
            montos.append(float(val))
        except:
            pass

    # Patrón 2: "saldo total" o "total a pagar" seguido de monto
    patron2 = re.findall(r'(?:saldo\s+total|total\s+a\s+pagar|monto\s+total|importe)\s*:?\s*\$?\s*([\d.]+(?:,\d{2})?)', texto, re.IGNORECASE)
    for m in patron2:
        try:
            val = m.replace('.', '').replace(',', '.')
            montos.append(float(val))
        except:
            pass

    return montos

def parse_vencimiento(texto):
    """Extrae fechas de vencimiento del texto."""
    fechas = []

    # Patrón: "vencimiento" seguido de fecha DD/MM o DD-MM o "el DD de MES"
    patrones = [
        r'venc\w*\s*:?\s*(\d{1,2})[/\-](\d{1,2})[/\-]?(\d{2,4})?',
        r'vence\s*(?:el\s+)?(\d{1,2})[/\-](\d{1,2})[/\-]?(\d{2,4})?',
        r'(\d{1,2})[/\-](\d{1,2})[/\-](\d{4})\s*(?:venc|vence)',
    ]

    for patron in patrones:
        matches = re.findall(patron, texto, re.IGNORECASE)
        for m in matches:
            try:
                dia = int(m[0])
                mes_num = int(m[1])
                anio = int(m[2]) if m[2] and len(m[2]) == 4 else datetime.now().year
                if 1 <= dia <= 31 and 1 <= mes_num <= 12:
                    fechas.append(f"{anio}-{mes_num:02d}-{dia:02d}")
            except:
                pass

    return fechas

def parse_pago_minimo(texto):
    """Extrae monto de pago mínimo."""
    patron = re.findall(r'pago\s+m[ií]n\w*\s*:?\s*\$?\s*([\d.]+(?:,\d{2})?)', texto, re.IGNORECASE)
    for m in patron:
        try:
            val = m.replace('.', '').replace(',', '.')
            return float(val)
        except:
            pass
    return None

def identify_card(texto, remitente):
    """Identifica qué tarjeta es basándose en el contenido del email."""
    texto_lower = texto.lower()

    if "cabal" in texto_lower or "xxxx-3923" in texto_lower:
        return "cabal_credicoop"
    if "visa" in texto_lower and ("xxxx-2384" in texto_lower or "credicoop" in remitente.lower()):
        if "nbsf" in texto_lower or "nuevo banco" in texto_lower or "santa fe" in texto_lower:
            return "visa_nbsf"
        return "visa_credicoop"
    if "master" in texto_lower and "nbsf" in texto_lower:
        return "master_nbsf_joa"
    if "visa" in texto_lower and ("nbsf" in texto_lower or "eresumen" in remitente.lower()):
        return "visa_nbsf"

    return None

def extract_pdf_from_email(msg, password):
    """Extrae y desencripta PDFs adjuntos de un email. Retorna lista de (filename, texto)."""
    if not HAS_PYPDF:
        return []

    results = []
    for part in msg.walk():
        cd = str(part.get("Content-Disposition", ""))
        if "attachment" not in cd:
            continue
        fn = part.get_filename()
        if not fn:
            continue

        fn_decoded = decode_header(fn)[0]
        fn_text = fn_decoded[0].decode(fn_decoded[1] or "utf-8", errors="replace") if isinstance(fn_decoded[0], bytes) else fn_decoded[0]

        if not fn_text.lower().endswith(".pdf"):
            continue

        pdf_bytes = part.get_payload(decode=True)
        if not pdf_bytes:
            continue

        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
                tmp.write(pdf_bytes)
                tmp_path = tmp.name

            reader = PdfReader(tmp_path)
            if reader.is_encrypted:
                result = reader.decrypt(password)
                if result == 0:
                    print(f"    ⚠ Clave incorrecta para {fn_text}")
                    os.unlink(tmp_path)
                    continue

            texto = ""
            for page in reader.pages:
                page_text = page.extract_text() or ""
                texto += page_text + "\n"

            os.unlink(tmp_path)
            results.append((fn_text, texto))
            print(f"    📎 PDF desencriptado: {fn_text}")

        except Exception as e:
            print(f"    ⚠ Error leyendo PDF {fn_text}: {e}")

    return results

def parse_credicoop_pdf(texto, filename):
    """Extrae datos del resumen de Credicoop desde el texto del PDF."""
    resultado = {"tarjeta": None, "monto": None, "pago_minimo": None, "vencimiento": None}

    filename_lower = filename.lower()
    if "cabal" in filename_lower:
        resultado["tarjeta"] = "cabal_credicoop"
    elif "visa" in filename_lower:
        resultado["tarjeta"] = "visa_credicoop"

    # Saldo actual — search for pattern near "SALDO ACTUAL"
    patron_saldo = re.findall(r'SALDO\s+ACTUAL\s+\$\s*([\d.]+(?:,\d{2})?)', texto, re.IGNORECASE)
    if not patron_saldo:
        patron_saldo = re.findall(r'DEBITAREMOS.*?\$\s*([\d.]+(?:,\d{2})?)', texto, re.IGNORECASE)
    if patron_saldo:
        try:
            val = patron_saldo[0].replace('.', '').replace(',', '.')
            resultado["monto"] = float(val)
        except:
            pass

    # Pago mínimo
    patron_min = re.findall(r'PAGO\s+M[IÍ]N\w*\s*(?:ACTUAL)?\s*\$?\s*([\d.]+(?:,\d{2})?)', texto, re.IGNORECASE)
    if patron_min:
        try:
            val = patron_min[0].replace('.', '').replace(',', '.')
            resultado["pago_minimo"] = float(val)
        except:
            pass

    # Vencimiento — buscar "VENCIMIENTO ACTUAL" o fecha cerca del nombre
    patron_venc = re.findall(r'(?:VENCIMIENTO\s+ACTUAL|Vence)\s*:?\s*(\d{1,2})[/\-\s]+(May|Jun|Jul|Abr|Ene|Feb|Mar|Sep|Oct|Nov|Dic|Ago)[a-z]*[/\-\s]*(\d{2,4})?', texto, re.IGNORECASE)
    if patron_venc:
        meses_map = {'ene':1,'feb':2,'mar':3,'abr':4,'may':5,'jun':6,'jul':7,'ago':8,'sep':9,'oct':10,'nov':11,'dic':12}
        for m in patron_venc:
            try:
                dia = int(m[0])
                mes = meses_map.get(m[1].lower()[:3])
                anio = int(m[2]) if m[2] and len(m[2]) == 4 else 2026
                if mes and 1 <= dia <= 31:
                    resultado["vencimiento"] = f"{anio}-{mes:02d}-{dia:02d}"
                    break
            except:
                pass

    # Fallback: buscar "XX May 26" pattern
    if not resultado["vencimiento"]:
        patron_fecha2 = re.findall(r'(\d{1,2})\s+(May|Jun|Jul|Abr)\s+(\d{2})', texto, re.IGNORECASE)
        meses_map = {'ene':1,'feb':2,'mar':3,'abr':4,'may':5,'jun':6,'jul':7,'ago':8,'sep':9,'oct':10,'nov':11,'dic':12}
        for m in patron_fecha2[:5]:  # primeros matches
            try:
                dia = int(m[0])
                mes = meses_map.get(m[1].lower()[:3])
                anio = 2000 + int(m[2])
                if mes and 1 <= dia <= 31:
                    resultado["vencimiento"] = f"{anio}-{mes:02d}-{dia:02d}"
                    break
            except:
                pass

    return resultado

# ── MAIN LOGIC ──

def run_check():
    """Ejecuta la verificación de mails. Retorna un dict con el resultado."""
    print(f"\n{'='*60}")
    print(f"CHECK MAILS - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*60}\n")

    # Cargar datos actuales
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    with open(GASTOS_FILE, "r", encoding="utf-8") as f:
        gastos = json.load(f)

    mes_actual = datetime.now().strftime("%Y-%m")
    mes_siguiente = None
    y, m = datetime.now().year, datetime.now().month
    if m == 12:
        mes_siguiente = f"{y+1}-01"
    else:
        mes_siguiente = f"{y}-{m+1:02d}"

    if mes_actual not in gastos["pagos"]:
        gastos["pagos"][mes_actual] = {}

    # Conectar a Gmail
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(GMAIL_USER, GMAIL_PASS)
        mail.select("inbox")
    except Exception as e:
        print(f"❌ Error conectando a Gmail: {e}")
        return {"error": str(e), "last_check": datetime.now().isoformat()}

    fecha_desde = (datetime.now() - timedelta(days=DIAS_ATRAS)).strftime("%d-%b-%Y")
    actualizaciones = []
    mails_procesados = 0

    # Buscar por cada remitente clave
    for remitente, gasto_ids in REMITENTE_MAP.items():
        criterio = f'(FROM "{remitente}" SINCE {fecha_desde})'
        try:
            _, data = mail.search(None, criterio)
        except Exception as e:
            print(f"⚠ Error buscando {remitente}: {e}")
            continue

        ids = data[0].split()
        if not ids:
            print(f"📭 {remitente} → sin mails nuevos")
            continue

        print(f"📧 {remitente} → {len(ids)} mail(s)")

        # Procesar los últimos 5 de cada remitente
        for uid in ids[-5:]:
            try:
                _, msg_data = mail.fetch(uid, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])
            except:
                continue

            asunto = decodificar_header(msg.get("Subject", ""))
            fecha_mail = msg.get("Date", "")
            texto = extraer_texto(msg)

            mails_procesados += 1
            print(f"  → [{fecha_mail[:16]}] {asunto[:70]}")

            # 1. Intentar leer PDFs adjuntos (Credicoop)
            pdfs = extract_pdf_from_email(msg, PDF_PASSWORD)
            for fn_text, pdf_texto in pdfs:
                datos_pdf = parse_credicoop_pdf(pdf_texto, fn_text)
                card_id = datos_pdf.get("tarjeta")
                if card_id and datos_pdf.get("monto"):
                    updates = {}
                    motivo = []
                    if datos_pdf["monto"]:
                        updates["monto"] = datos_pdf["monto"]
                        motivo.append(f"monto ${datos_pdf['monto']:,.0f}")
                    if datos_pdf.get("pago_minimo"):
                        updates["pago_minimo"] = datos_pdf["pago_minimo"]
                        motivo.append(f"mínimo ${datos_pdf['pago_minimo']:,.0f}")
                    if datos_pdf.get("vencimiento"):
                        updates["vencimiento"] = datos_pdf["vencimiento"]
                        motivo.append(f"vence {datos_pdf['vencimiento']}")
                    updates["fuente"] = f"pdf:{remitente}"

                    if updates:
                        if card_id not in gastos["pagos"].get(target_mes, {}):
                            if target_mes not in gastos["pagos"]:
                                gastos["pagos"][target_mes] = {}
                            gastos["pagos"][target_mes][card_id] = {"pagado": False}
                        for key, val in updates.items():
                            gastos["pagos"][target_mes][card_id][key] = val
                        actualizaciones.append({
                            "gasto_id": card_id,
                            "mes": target_mes,
                            "updates": updates,
                            "asunto": asunto[:80] + f" [PDF: {fn_text}]",
                            "fecha_mail": fecha_mail[:30]
                        })
                        print(f"    ✓ {card_id} (PDF): {', '.join(motivo)}")

            # 2. Si no se extrajo del PDF, intentar del texto del email
            card_id = identify_card(texto, remitente)

            # Si el remitente está mapeado a un solo gasto, usar ese
            if len(gasto_ids) == 1 and not card_id:
                card_id = gasto_ids[0]

            # Si identify_card no encontró nada pero el remitente tiene múltiples,
            # intentar por asunto
            if not card_id and len(gasto_ids) > 1:
                asunto_lower = asunto.lower()
                if "cabal" in asunto_lower or "cabal" in texto[:200].lower():
                    card_id = "cabal_credicoop"
                elif "visa" in asunto_lower:
                    card_id = "visa_credicoop"

            if not card_id:
                print(f"    ⚠ No se pudo identificar el gasto. Remitente: {remitente}")
                continue

            # Determinar a qué mes corresponde (usar mes actual por defecto)
            target_mes = mes_actual

            # Extraer datos del email
            montos = parse_monto_ars(texto)
            vencimientos = parse_vencimiento(texto)
            pago_minimo = parse_pago_minimo(texto)

            # Decidir qué actualizar
            updates = {}
            motivo = []

            # Monto: usar el monto más grande encontrado (suele ser el saldo total)
            if montos:
                monto_max = max(montos)
                # Verificar si ya hay un monto y si este es diferente
                existing = gastos["pagos"].get(target_mes, {}).get(card_id, {})
                existing_monto = existing.get("monto")
                if not existing_monto or abs(monto_max - existing_monto) > 100:
                    updates["monto"] = monto_max
                    motivo.append(f"monto ${monto_max:,.0f}")

            # Vencimiento
            if vencimientos:
                # Tomar el primer vencimiento encontrado que sea futuro
                hoy = datetime.now()
                for v in sorted(vencimientos):
                    try:
                        vdate = datetime.strptime(v, "%Y-%m-%d")
                        if vdate >= hoy - timedelta(days=5):  # permitir fechas recién pasadas
                            updates["vencimiento"] = v
                            motivo.append(f"vence {v}")
                            break
                    except:
                        pass

            # Pago mínimo
            if pago_minimo:
                updates["pago_minimo"] = pago_minimo
                motivo.append(f"mínimo ${pago_minimo:,.0f}")

            # Fuente
            updates["fuente"] = f"gmail:{remitente}"

            # Aplicar actualizaciones
            if updates:
                if card_id not in gastos["pagos"].get(target_mes, {}):
                    if target_mes not in gastos["pagos"]:
                        gastos["pagos"][target_mes] = {}
                    gastos["pagos"][target_mes][card_id] = {"pagado": False}

                # Solo actualizar campos que tengamos info nueva
                for key, val in updates.items():
                    if key == "fuente":
                        # Siempre actualizar la fuente
                        gastos["pagos"][target_mes][card_id][key] = val
                    elif key in ["monto", "vencimiento", "pago_minimo"]:
                        # Solo actualizar si no existe o es None
                        existing_val = gastos["pagos"][target_mes][card_id].get(key)
                        if existing_val is None or existing_val is False:
                            gastos["pagos"][target_mes][card_id][key] = val
                        elif key == "monto" and val and existing_val and abs(val - existing_val) > 100:
                            # Si el monto cambió significativamente, actualizar
                            gastos["pagos"][target_mes][card_id][key] = val

                # Si el monto es nuevo, actualizar notas
                if "monto" in updates and "notas" not in updates:
                    notas = asunto[:80]
                    gastos["pagos"][target_mes][card_id].setdefault("notas", notas)

                actualizaciones.append({
                    "gasto_id": card_id,
                    "mes": target_mes,
                    "updates": updates,
                    "asunto": asunto[:80],
                    "fecha_mail": fecha_mail[:30]
                })
                print(f"    ✓ {card_id}: {', '.join(motivo)}")

    mail.logout()

    # Guardar gastos.json si hubo cambios
    if actualizaciones:
        # Backup
        bak = GASTOS_FILE + ".bak"
        if os.path.exists(GASTOS_FILE):
            shutil.copy2(GASTOS_FILE, bak)

        gastos["ultima_actualizacion"] = datetime.now().strftime("%Y-%m-%d")

        with open(GASTOS_FILE, "w", encoding="utf-8") as f:
            json.dump(gastos, f, indent=2, ensure_ascii=False)

        print(f"\n✅ {len(actualizaciones)} actualización(es) guardadas en gastos.json")
    else:
        print(f"\n📭 No se encontraron datos nuevos para actualizar")

    # Guardar log
    log_data = {
        "last_check": datetime.now().isoformat(),
        "mails_procesados": mails_procesados,
        "actualizaciones": actualizaciones,
        "dias_atras": DIAS_ATRAS
    }
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log_data, f, indent=2, ensure_ascii=False)

    print(f"📋 Log guardado en check_mails_log.json")
    print(f"{'='*60}\n")

    return log_data


if __name__ == "__main__":
    run_check()
