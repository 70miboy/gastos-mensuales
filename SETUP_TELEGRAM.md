# Setup del Bot de Telegram para Gastos Mensuales

## Paso 1: Crear el bot en Telegram

1. Abrí Telegram en el celular o PC
2. Buscá **@BotFather** y abrí un chat
3. Enviá: `/newbot`
4. BotFather pregunta el nombre → respondé: `Gastos Tomi Bot`
5. BotFather pregunta el username → respondé: `gastos_tomi_bot` (debe terminar en "bot")
6. BotFather te responde con un **token** tipo: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`
7. Copiá ese token

## Paso 2: Guardar el token

1. En la carpeta del proyecto, creá un archivo llamado `telegram_bot_token.txt`
2. Pegá el token adentro (solo el token, sin espacios ni comillas)
3. Guardá

## Paso 3: Obtener tu chat_id

1. Ya con el bot creado, mandale `/start` desde Telegram al bot
2. Ejecutá `python telegram_bot.py` — el bot va a responder con tu chat_id
3. Anotá ese número (ej: `987654321`)
4. Creá un archivo `telegram_allowed_chats.txt` y pegá ese número adentro
5. Reiniciá el bot

## Paso 4: Usar el bot

Desde el celular, en Telegram, mandá mensajes al bot:

```
/pago ubajay 268623
/pago visa_credicoop 293377 13/05
/monto visa_credicoop 1412842 13/05
/nuevo internet_claro "Internet Claro" servicio Tomás 45000 15/06
/pendientes
/hoy
```

## Ejecutar

```bash
# Iniciar el bot (queda corriendo)
python telegram_bot.py

# Para que corra junto con el server:
# Terminal 1: python server.py
# Terminal 2: python telegram_bot.py
```

## Para que funcione 24/7 (sin la PC prendida)

Deploy gratis en Render.com:
1. Crear cuenta en render.com
2. Crear un "Web Service" desde el repo de GitHub
3. Configurar: Start Command = `python telegram_bot.py`
4. Agregar env var: TELEGRAM_BOT_TOKEN = tu token
5. Listo, corre 24/7 gratis
