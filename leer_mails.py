"""
Script para leer mails relevantes de gastos desde Gmail via IMAP.
Uso: python leer_mails.py
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
import imaplib
import email
from email.header import decode_header
import json
import re
from datetime import datetime, timedelta

# ── CONFIG ──
# Las credenciales se resuelven en gmail_auth (variable de entorno o archivo
# local ignorado por git). Nunca escribirlas en este archivo.
from gmail_auth import GMAIL_USER, get_gmail_pass

GMAIL_PASS = get_gmail_pass()

REMITENTES_CLAVE = [
    "estudio.ormachea@gmail.com",
    "diegoormachea@hotmail.com",
    "info@eresumen.com",
    "asociados@bancocredicoop.coop",
    "mensajesyalertas@bancocredicoop.coop",
    "banco@bancojulio.com.ar",
    "noreply@consorcioabierto.com",
    "oficinavirtual@epe.santafe.gov.ar",
]

DIAS_ATRAS = 60  # cuántos días hacia atrás buscar

def conectar():
    mail = imaplib.IMAP4_SSL("imap.gmail.com")
    mail.login(GMAIL_USER, GMAIL_PASS)
    return mail

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
    else:
        try:
            texto = msg.get_payload(decode=True).decode("utf-8", errors="replace")
        except:
            pass
    return texto[:3000]  # limitamos para no gastar tokens

def buscar_mails():
    print(f"\n{'='*60}")
    print(f"LECTURA DE MAILS - {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*60}\n")

    mail = conectar()
    mail.select("inbox")

    fecha_desde = (datetime.now() - timedelta(days=DIAS_ATRAS)).strftime("%d-%b-%Y")
    resultados = []

    for remitente in REMITENTES_CLAVE:
        criterio = f'(FROM "{remitente}" SINCE {fecha_desde})'
        _, data = mail.search(None, criterio)
        ids = data[0].split()

        if not ids:
            continue

        print(f"📧 {remitente} → {len(ids)} mail(s)")

        # Tomar los últimos 3 de cada remitente
        for uid in ids[-3:]:
            _, msg_data = mail.fetch(uid, "(RFC822)")
            msg = email.message_from_bytes(msg_data[0][1])

            asunto = decodificar_header(msg.get("Subject", ""))
            fecha = msg.get("Date", "")
            texto = extraer_texto(msg)

            resultados.append({
                "remitente": remitente,
                "asunto": asunto,
                "fecha": fecha,
                "texto": texto
            })

            print(f"  → [{fecha[:16]}] {asunto[:70]}")

    mail.logout()

    print(f"\n{'='*60}")
    print(f"TOTAL: {len(resultados)} mails encontrados")
    print(f"{'='*60}\n")

    # Guardar resultado para que Claude lo procese
    output = []
    for m in resultados:
        output.append(f"--- MAIL ---")
        output.append(f"De: {m['remitente']}")
        output.append(f"Asunto: {m['asunto']}")
        output.append(f"Fecha: {m['fecha']}")
        output.append(f"Contenido:")
        output.append(m['texto'])
        output.append("")

    resultado_texto = "\n".join(output)
    
    # Guardar en archivo
    with open("mails_resultado.txt", "w", encoding="utf-8") as f:
        f.write(resultado_texto)

    print(resultado_texto[:5000])  # mostrar en consola también
    print(f"\n✅ Resultado guardado en mails_resultado.txt")
    print(f"Pegá ese contenido a Claude para que procese los vencimientos.")

if __name__ == "__main__":
    buscar_mails()
