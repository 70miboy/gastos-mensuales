import sys, io, imaplib, email, re
from email.header import decode_header
from gmail_auth import GMAIL_USER, get_gmail_pass
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

mail = imaplib.IMAP4_SSL('imap.gmail.com')
mail.login(GMAIL_USER, get_gmail_pass())
mail.select('inbox')

_, data = mail.search(None, '(FROM "info@eresumen.com" SINCE 01-Jul-2026)')
ids = data[0].split()
print(f"Mails encontrados: {len(ids)}")

for uid in ids:
    _, msg_data = mail.fetch(uid, '(RFC822)')
    msg = email.message_from_bytes(msg_data[0][1])
    asunto_raw = decode_header(msg.get('Subject',''))[0]
    asunto = asunto_raw[0].decode(asunto_raw[1] or 'utf-8', errors='replace') if isinstance(asunto_raw[0], bytes) else asunto_raw[0]
    fecha = msg.get('Date','')
    print(f"\n=== {fecha} === {asunto} ===")
    
    texto = ''
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get('Content-Disposition',''))
            if ct in ('text/plain', 'text/html') and 'attachment' not in cd:
                try: 
                    payload = part.get_payload(decode=True)
                    if payload:
                        texto += payload.decode('utf-8', errors='replace')
                except: pass
    else:
        try: 
            payload = msg.get_payload(decode=True)
            if payload:
                texto = payload.decode('utf-8', errors='replace')
        except: pass
    
    # Buscar vencimiento y totales
    venc_match = re.search(r'vencimiento[\s\S]{0,200}?(\d{2}/\d{2}/\d{4}|\d{2}-\d{2}-\d{4})', texto, re.IGNORECASE)
    total_match = re.search(r'total[\s\S]{0,200}?\$[\s.\d,]+', texto, re.IGNORECASE)
    pago_min_match = re.search(r'pago m[íi]nimo[\s\S]{0,200}?\$[\s.\d,]+', texto, re.IGNORECASE)
    saldo_match = re.search(r'saldo[\s\S]{0,200}?\$[\s.\d,]+', texto, re.IGNORECASE)
    
    if venc_match: print(f"Vencimiento encontrado: {venc_match.group(1)}")
    if total_match: print(f"Total encontrado: {total_match.group(0)}")
    if pago_min_match: print(f"Pago mínimo: {pago_min_match.group(0)}")
    if saldo_match: print(f"Saldo: {saldo_match.group(0)}")
    
    # Mostrar todo el texto para análisis manual
    print("\n--- TEXTO COMPLETO ---")
    print(texto)

mail.logout()
