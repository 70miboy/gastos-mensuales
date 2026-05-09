"""
Extrae y desencripta PDFs adjuntos de Credicoop para obtener montos.
Uso: python leer_pdfs_credicoop.py
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import imaplib
import email
from email.header import decode_header
import os
import tempfile
from pypdf import PdfReader

GMAIL_USER = "tominorman@gmail.com"
GMAIL_PASS = "wjpj bolj qbvl wykd"
PDF_PASSWORD = "29834279"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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

def extract_pdf_text(pdf_bytes, password):
    """Extrae texto de un PDF encriptado."""
    try:
        # Escribir a archivo temporal
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(pdf_bytes)
            tmp_path = tmp.name

        reader = PdfReader(tmp_path)

        # Desencriptar si es necesario
        if reader.is_encrypted:
            result = reader.decrypt(password)
            if result == 0:
                print("  ❌ Clave incorrecta para el PDF")
                os.unlink(tmp_path)
                return None
            print("  ✓ PDF desencriptado correctamente")

        # Extraer texto de todas las páginas
        texto = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                texto += page_text + "\n"

        os.unlink(tmp_path)
        return texto

    except Exception as e:
        print(f"  ❌ Error leyendo PDF: {e}")
        return None

def parse_credicoop_pdf(texto, asunto):
    """Extrae datos del resumen de Credicoop desde el texto del PDF."""
    resultado = {"tarjeta": None, "monto": None, "pago_minimo": None, "vencimiento": None}

    # Identificar tarjeta
    texto_lower = texto.lower()
    if "cabal" in texto_lower or "xxxx-xxxx-xxxx-3923" in texto:
        resultado["tarjeta"] = "cabal_credicoop"
    elif "visa" in texto_lower or "xxxx-xxxx-xxxx-2384" in texto:
        resultado["tarjeta"] = "visa_credicoop"

    # Buscar saldo facturado / total
    import re
    patron_saldo = re.findall(r'(?:saldo\s+facturado|saldo\s+total|total\s+a\s+pagar)\s*(?:en\s+pesos)?\s*\$?\s*([\d.]+(?:,\d{2})?)', texto, re.IGNORECASE)
    if patron_saldo:
        val = patron_saldo[0].replace('.', '').replace(',', '.')
        try:
            resultado["monto"] = float(val)
        except:
            pass

    # Pago mínimo
    patron_min = re.findall(r'pago\s+m[ií]nimo\s*(?:en\s+pesos)?\s*\$?\s*([\d.]+(?:,\d{2})?)', texto, re.IGNORECASE)
    if patron_min:
        val = patron_min[0].replace('.', '').replace(',', '.')
        try:
            resultado["pago_minimo"] = float(val)
        except:
            pass

    # Vencimiento
    patron_venc = re.findall(r'venc\w*\s*:?\s*(\d{1,2})[/\-](\d{1,2})[/\-]?(\d{2,4})?', texto, re.IGNORECASE)
    if patron_venc:
        for m in patron_venc:
            try:
                dia = int(m[0])
                mes = int(m[1])
                anio = int(m[2]) if m[2] and len(m[2]) == 4 else 2026
                if 1 <= dia <= 31 and 1 <= mes <= 12:
                    resultado["vencimiento"] = f"{anio}-{mes:02d}-{dia:02d}"
                    break
            except:
                pass

    return resultado

def main():
    print(f"\n{'='*60}")
    print("LECTURA PDFs CREDICOOP")
    print(f"{'='*60}\n")

    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_USER, GMAIL_PASS)
    mail.select("inbox")

    # Buscar mails de Credicoop con PDFs
    _, data = mail.search(None, '(FROM "asociados@bancocredicoop.coop" SINCE 01-Apr-2026)')
    ids = data[0].split()
    print(f"📧 {len(ids)} mail(s) de Credicoop asociados\n")

    resultados = []

    for uid in ids[-5:]:
        _, msg_data = mail.fetch(uid, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        asunto = decodificar_header(msg.get("Subject", ""))
        fecha = msg.get("Date", "")[:30]

        print(f"→ [{fecha}] {asunto[:70]}")

        # Buscar PDFs adjuntos
        for part in msg.walk():
            cd = str(part.get("Content-Disposition", ""))
            if "attachment" in cd:
                fn = part.get_filename()
                if fn:
                    fn_decoded = decode_header(fn)
                    fn_text = fn_decoded[0][0].decode(fn_decoded[0][1] or "utf-8", errors="replace") if isinstance(fn_decoded[0][0], bytes) else fn_decoded[0][0]

                    if fn_text.lower().endswith(".pdf"):
                        print(f"  📎 PDF: {fn_text}")
                        pdf_bytes = part.get_payload(decode=True)
                        if pdf_bytes:
                            texto = extract_pdf_text(pdf_bytes, PDF_PASSWORD)
                            if texto:
                                datos = parse_credicoop_pdf(texto, asunto)
                                datos["asunto"] = asunto
                                datos["fecha_mail"] = fecha
                                resultados.append(datos)
                                print(f"  📊 Tarjeta: {datos['tarjeta']}")
                                print(f"     Monto: {datos['monto']}")
                                print(f"     Pago mín: {datos['pago_minimo']}")
                                print(f"     Vence: {datos['vencimiento']}")
                                # Mostrar fragmento del texto
                                lines = [l.strip() for l in texto.split('\n') if l.strip()][:30]
                                print(f"     Texto (primeras líneas):")
                                for line in lines:
                                    print(f"       {line[:100]}")
                    else:
                        print(f"  📎 Otro: {fn_text}")

    mail.logout()

    print(f"\n{'='*60}")
    print(f"RESULTADO: {len(resultados)} PDF(s) procesados")
    for r in resultados:
        print(f"  {r.get('tarjeta','?')}: monto={r.get('monto')}, venc={r.get('vencimiento')}")
    print(f"{'='*60}\n")

    return resultados

if __name__ == "__main__":
    main()
