import sys, io, imaplib, email
from email.header import decode_header
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

mail = imaplib.IMAP4_SSL('imap.gmail.com')
mail.login('tominorman@gmail.com', 'wjpj bolj qbvl wykd')
mail.select('inbox')

remitentes = [
    'banco@bancojulio.com.ar',
    'asociados@bancocredicoop.coop',
    'mensajesyalertas@bancocredicoop.coop',
]

for remitente in remitentes:
    _, data = mail.search(None, f'(FROM "{remitente}" SINCE 01-Apr-2026)')
    ids = data[0].split()
    for uid in ids[-2:]:
        _, msg_data = mail.fetch(uid, '(RFC822)')
        msg = email.message_from_bytes(msg_data[0][1])
        asunto_raw = decode_header(msg.get('Subject',''))[0]
        asunto = asunto_raw[0].decode(asunto_raw[1] or 'utf-8', errors='replace') if isinstance(asunto_raw[0], bytes) else asunto_raw[0]
        fecha = msg.get('Date','')[:30]
        texto = ''
        if msg.is_multipart():
            for part in msg.walk():
                ct = part.get_content_type()
                cd = str(part.get('Content-Disposition',''))
                if ct == 'text/plain' and 'attachment' not in cd:
                    try: texto += part.get_payload(decode=True).decode('utf-8', errors='replace')
                    except: pass
        else:
            try: texto = msg.get_payload(decode=True).decode('utf-8', errors='replace')
            except: pass
        print(f'=== {remitente} ===')
        print(f'Asunto: {asunto}')
        print(f'Fecha: {fecha}')
        print(texto[:2000])
        print()

mail.logout()
