"""
Bot de Telegram para registrar gastos desde el celular.
Cero tokens, parseo con regex, actualiza gastos.json directamente.
Usa short-polling manual (sin python-telegram-bot) para evitar 409 Conflict.

Uso: python telegram_bot.py

Comandos:
  /pago <gasto> <monto> [fecha]    - Registrar un pago
  /monto <gasto> <monto> [fecha]   - Actualizar monto/vencimiento
  /nuevo <id> <nombre> <cat> <persona> <monto> <venc> - Agregar gasto nuevo
  /pendientes                      - Ver gastos pendientes del mes
  /hoy                             - Ver qué vence hoy/mañana
  /status                          - Resumen del mes
  /help                            - Ayuda

Ejemplos:
  /pago ubajay 268623
  /pago visa_credicoop 293377 13/05
  /monto visa_credicoop 1412842 13/05
  /nuevo internet_claro "Internet Claro" servicio Tomás 45000 15/06
  /pendientes
  /hoy
"""

import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import json
import os
import re
import shutil
import logging
import time
import atexit
import signal
from datetime import datetime, date
import httpx

# ── PATHS: soporta volumen persistente en Fly.io o local ──
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GASTOS_FILE = os.path.join(DATA_DIR, "gastos.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
LOCK_FILE = os.path.join(DATA_DIR, "telegram_bot.lock")

# ── LOCKFILE: evita múltiples instancias ──
def acquire_lock():
    """Crea un lockfile con el PID actual. Si ya existe y el proceso sigue vivo, aborta."""
    import ctypes
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE, "r") as f:
                old_pid = int(f.read().strip())
            # Verificar si el proceso sigue corriendo (Windows)
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(1, False, old_pid)  # 1 = PROCESS_TERMINATE
            if handle:
                kernel32.CloseHandle(handle)
                print(f"⚠ Ya hay una instancia del bot corriendo (PID {old_pid}).")
                print("   Si el bot se cerró mal, borrá el archivo: telegram_bot.lock")
                sys.exit(1)
            else:
                print(f"🧹 Lockfile de PID {old_pid} obsoleto, eliminando...")
                os.remove(LOCK_FILE)
        except (ValueError, OSError):
            os.remove(LOCK_FILE)
    
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    print(f"🔒 Lockfile creado (PID {os.getpid()})")

def release_lock():
    """Elimina el lockfile al cerrar."""
    if os.path.exists(LOCK_FILE):
        try:
            os.remove(LOCK_FILE)
            print("🔓 Lockfile liberado")
        except OSError:
            pass

# Registrar cleanup al salir
atexit.register(release_lock)

# Cleanup al recibir señales de terminación
def signal_handler(signum, frame):
    print(f"\n⚡ Señal {signum} recibida, cerrando bot...")
    release_lock()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ── BOT TOKEN ──
BOT_TOKEN_FILE = os.environ.get("BOT_TOKEN_FILE", os.path.join(DATA_DIR, "telegram_bot_token.txt"))
if os.path.exists(BOT_TOKEN_FILE):
    BOT_TOKEN = open(BOT_TOKEN_FILE, "r").read().strip()
else:
    BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not BOT_TOKEN:
        print("⚠ BOT TOKEN no configurado. Set TELEGRAM_BOT_TOKEN env var o creá telegram_bot_token.txt")

# ── AUTHORIZED USERS ──
ALLOWED_CHAT_IDS_FILE = os.environ.get("ALLOWED_CHATS_FILE", os.path.join(DATA_DIR, "telegram_allowed_chats.txt"))
def get_allowed_chats():
    if os.path.exists(ALLOWED_CHAT_IDS_FILE):
        return [int(x.strip()) for x in open(ALLOWED_CHAT_IDS_FILE) if x.strip().isdigit()]
    return []

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ── HELPERS ──

def read_gastos():
    with open(GASTOS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def write_gastos(data):
    bak = GASTOS_FILE + ".bak"
    if os.path.exists(GASTOS_FILE):
        shutil.copy2(GASTOS_FILE, bak)
    with open(GASTOS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def read_config():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def fmt(n):
    if not n: return "—"
    return f"${n:,.0f}".replace(",", ".")

def fmt_date(s):
    if not s: return "—"
    y, m, d = s.split("-")
    return f"{d}/{m}"

def parse_fecha(text):
    """Parsea fecha en formato DD/MM o YYYY-MM-DD."""
    if not text:
        return None
    m = re.match(r'^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$', text)
    if m:
        dia, mes = int(m.group(1)), int(m.group(2))
        anio = int(m.group(3)) if m.group(3) else date.today().year
        if len(str(anio)) == 2:
            anio = 2000 + anio
        return f"{anio}-{mes:02d}-{dia:02d}"
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', text)
    if m:
        return text
    return None

def find_gasto_id(text, gastos_list):
    """Busca un gasto por ID parcial o nombre parcial."""
    text_lower = text.lower().strip()
    for g in gastos_list:
        if g["id"] == text_lower:
            return g
    for g in gastos_list:
        if text_lower in g["id"]:
            return g
    for g in gastos_list:
        if text_lower in g["nombre"].lower():
            return g
    for g in gastos_list:
        keywords = g["id"].replace("_", " ").split()
        if any(k in text_lower for k in keywords):
            return g
    return None

def is_authorized(chat_id):
    allowed = get_allowed_chats()
    if not allowed:
        return True  # modo setup
    return chat_id in allowed

def send_msg(chat_id, text):
    """Send a message via Telegram API."""
    try:
        httpx.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as e:
        logger.error(f"send_msg error: {e}")

# ── COMMAND HANDLERS (sync, no library) ──

def handle_start(chat_id):
    send_msg(chat_id,
        "💰 *Gastos Mensuales Bot*\n\n"
        f"Tu chat_id: `{chat_id}`\n"
        "Guardalo en telegram_allowed_chats.txt\n\n"
        "Comandos:\n"
        "/pago \\[gasto] \\[monto] \\[fecha]\n"
        "/monto \\[gasto] \\[monto] \\[fecha]\n"
        "/pendientes\n"
        "/hoy\n"
        "/status\n"
        "/help"
    )

def handle_help(chat_id):
    send_msg(chat_id,
        "💰 *Comandos*\n\n"
        "*Registrar un pago:*\n"
        "/pago ubajay 268623\n"
        "/pago visa_credicoop 293377 13/05\n\n"
        "*Actualizar monto/vencimiento:*\n"
        "/monto visa_credicoop 1412842 13/05\n\n"
        "*Agregar gasto nuevo:*\n"
        "/nuevo internet_claro \"Internet Claro\" servicio Tomás 45000 15/06\n\n"
        "*Consultar:*\n"
        "/pendientes\n/hoy\n/status\n\n"
        "*Nombres abreviados funcionan:*\n"
        "visa, cabal, ubajay, epe, ormachea, etc."
    )

def handle_pago(chat_id, args):
    if not is_authorized(chat_id):
        send_msg(chat_id, "⛔ No autorizado")
        return
    if len(args) < 2:
        send_msg(chat_id, "❌ Formato: /pago <gasto> <monto> [fecha]\nEj: /pago ubajay 268623")
        return

    gasto_text = args[0]
    monto_str = args[1].replace(".", "").replace(",", ".")
    fecha_str = args[2] if len(args) > 2 else None

    try:
        monto = float(monto_str)
    except ValueError:
        send_msg(chat_id, f"❌ Monto inválido: {args[1]}")
        return

    fecha_pago = parse_fecha(fecha_str) or date.today().isoformat()
    mes_key = date.today().strftime("%Y-%m")

    config = read_config()
    gasto = find_gasto_id(gasto_text, config.get("gastos_recurrentes", []))
    if not gasto:
        nombres = ", ".join(g["id"] for g in config.get("gastos_recurrentes", [])[:8])
        send_msg(chat_id, f"❌ No encontré '{gasto_text}'. Nombres: {nombres}")
        return

    gastos = read_gastos()
    if mes_key not in gastos["pagos"]:
        gastos["pagos"][mes_key] = {}
    if gasto["id"] not in gastos["pagos"][mes_key]:
        gastos["pagos"][mes_key][gasto["id"]] = {"pagado": False}

    gastos["pagos"][mes_key][gasto["id"]].update({
        "pagado": True, "pagado_fecha": fecha_pago, "pagado_monto": monto
    })
    gastos["ultima_actualizacion"] = date.today().isoformat()
    write_gastos(gastos)

    send_msg(chat_id,
        f"✅ *{gasto['nombre']}*\n💰 Pagado: {fmt(monto)}\n📅 {fmt_date(fecha_pago)}"
    )

def handle_monto(chat_id, args):
    if not is_authorized(chat_id):
        send_msg(chat_id, "⛔ No autorizado")
        return
    if len(args) < 2:
        send_msg(chat_id, "❌ Formato: /monto <gasto> <monto> [fecha]\nEj: /monto visa_credicoop 1412842 13/05")
        return

    gasto_text = args[0]
    monto_str = args[1].replace(".", "").replace(",", ".")
    fecha_str = args[2] if len(args) > 2 else None

    try:
        monto = float(monto_str)
    except ValueError:
        send_msg(chat_id, f"❌ Monto inválido: {args[1]}")
        return

    fecha_venc = parse_fecha(fecha_str)
    mes_key = date.today().strftime("%Y-%m")

    config = read_config()
    gasto = find_gasto_id(gasto_text, config.get("gastos_recurrentes", []))
    if not gasto:
        send_msg(chat_id, f"❌ No encontré '{gasto_text}'")
        return

    gastos = read_gastos()
    if mes_key not in gastos["pagos"]:
        gastos["pagos"][mes_key] = {}
    if gasto["id"] not in gastos["pagos"][mes_key]:
        gastos["pagos"][mes_key][gasto["id"]] = {"pagado": False}

    gastos["pagos"][mes_key][gasto["id"]]["monto"] = monto
    if fecha_venc:
        gastos["pagos"][mes_key][gasto["id"]]["vencimiento"] = fecha_venc
    gastos["ultima_actualizacion"] = date.today().isoformat()
    write_gastos(gastos)

    msg = f"✅ *{gasto['nombre']}* actualizado\n💰 Monto: {fmt(monto)}"
    if fecha_venc:
        msg += f"\n📅 Vence: {fmt_date(fecha_venc)}"
    send_msg(chat_id, msg)

def handle_nuevo(chat_id, args):
    if not is_authorized(chat_id):
        send_msg(chat_id, "⛔ No autorizado")
        return
    if len(args) < 4:
        send_msg(chat_id,
            '❌ Formato: /nuevo <id> <nombre> <cat> <persona> [monto] [venc]\n'
            'Ej: /nuevo internet_claro "Internet Claro" servicio Tomás 45000 15/06'
        )
        return

    gasto_id = args[0].lower().replace(" ", "_")
    nombre = args[1].strip('"')
    categoria = args[2]
    persona = args[3]
    monto = None
    vencimiento = None

    if len(args) > 4:
        try:
            monto = float(args[4].replace(".", "").replace(",", "."))
        except:
            pass
    if len(args) > 5:
        vencimiento = parse_fecha(args[5])

    config = read_config()
    existing = [g["id"] for g in config.get("gastos_recurrentes", [])]
    if gasto_id in existing:
        send_msg(chat_id, f"❌ Ya existe '{gasto_id}'")
        return

    config.setdefault("gastos_recurrentes", []).append({
        "id": gasto_id, "nombre": nombre, "categoria": categoria,
        "persona": persona, "gmail_busqueda": [nombre],
        "dia_vencimiento_aprox": None, "activo": True
    })
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    gastos = read_gastos()
    mes_key = date.today().strftime("%Y-%m")
    if mes_key not in gastos["pagos"]:
        gastos["pagos"][mes_key] = {}
    gastos["pagos"][mes_key][gasto_id] = {
        "vencimiento": vencimiento, "monto": monto, "pagado": False,
        "pagado_fecha": None, "pagado_monto": None,
        "fuente": "carga_telegram", "notas": "Creado via Telegram bot"
    }
    gastos["ultima_actualizacion"] = date.today().isoformat()
    write_gastos(gastos)

    msg = f"✅ *Nuevo: {nombre}*\n🆔 {gasto_id} · 📂 {categoria} · 👤 {persona}"
    if monto:
        msg += f"\n💰 {fmt(monto)}"
    if vencimiento:
        msg += f"\n📅 {fmt_date(vencimiento)}"
    send_msg(chat_id, msg)

def handle_pendientes(chat_id):
    if not is_authorized(chat_id):
        send_msg(chat_id, "⛔ No autorizado")
        return

    gastos = read_gastos()
    config = read_config()
    mes_key = date.today().strftime("%Y-%m")
    mes_data = gastos["pagos"].get(mes_key, {})
    gastos_list = config.get("gastos_recurrentes", [])
    hoy = date.today()

    pendientes = []
    for g in gastos_list:
        p = mes_data.get(g["id"], {})
        if p.get("pagado") == True:
            continue
        venc = p.get("vencimiento")
        dias = None
        if venc:
            try:
                vdate = datetime.strptime(venc, "%Y-%m-%d").date()
                dias = (vdate - hoy).days
            except:
                pass
        pendientes.append((g, p, dias))

    if not pendientes:
        send_msg(chat_id, "🎉 ¡Todos los gastos del mes están pagados!")
        return

    pendientes.sort(key=lambda x: x[2] if x[2] is not None else 999)
    lines = [f"📋 *Pendientes — {mes_key}*"]
    for g, p, dias in pendientes:
        emoji = "🔴" if dias is not None and dias <= 1 else \
                "🟠" if dias is not None and dias <= 5 else \
                "🟡" if dias is not None and dias <= 10 else "⚪"
        dias_str = f"{dias}d" if dias is not None else "?"
        monto_str = fmt(p.get("monto")) if p.get("monto") else "sin monto"
        venc_str = fmt_date(p.get("vencimiento")) if p.get("vencimiento") else "sin fecha"
        lines.append(f"{emoji} *{g['nombre']}* · {monto_str} · vence {venc_str} · {dias_str}")

    send_msg(chat_id, "\n".join(lines))

def handle_hoy(chat_id):
    if not is_authorized(chat_id):
        send_msg(chat_id, "⛔ No autorizado")
        return

    gastos = read_gastos()
    config = read_config()
    mes_key = date.today().strftime("%Y-%m")
    mes_data = gastos["pagos"].get(mes_key, {})
    gastos_list = config.get("gastos_recurrentes", [])
    hoy = date.today()

    urgentes = []
    for g in gastos_list:
        p = mes_data.get(g["id"], {})
        if p.get("pagado") == True:
            continue
        venc = p.get("vencimiento")
        if not venc:
            continue
        try:
            vdate = datetime.strptime(venc, "%Y-%m-%d").date()
            dias = (vdate - hoy).days
            if dias <= 2:
                urgentes.append((g, p, dias))
        except:
            pass

    if not urgentes:
        send_msg(chat_id, "✅ Nada urgente por ahora.")
        return

    urgentes.sort(key=lambda x: x[2])
    lines = ["🚨 *URGENTE*"]
    for g, p, dias in urgentes:
        when = "HOY" if dias == 0 else "MAÑANA" if dias == 1 else f"en {dias}d"
        monto_str = fmt(p.get("monto")) if p.get("monto") else ""
        lines.append(f"🔴 *{g['nombre']}* {monto_str} — {when}")

    send_msg(chat_id, "\n".join(lines))

def handle_status(chat_id):
    if not is_authorized(chat_id):
        send_msg(chat_id, "⛔ No autorizado")
        return

    gastos = read_gastos()
    config = read_config()
    mes_key = date.today().strftime("%Y-%m")
    mes_data = gastos["pagos"].get(mes_key, {})
    gastos_list = config.get("gastos_recurrentes", [])

    total_known = 0
    total_paid = 0
    count_paid = 0
    count_pending = 0

    for g in gastos_list:
        p = mes_data.get(g["id"], {})
        if p.get("monto"):
            total_known += p["monto"]
        if p.get("pagado") == True:
            total_paid += p.get("pagado_monto") or p.get("monto") or 0
            count_paid += 1
        else:
            count_pending += 1

    pct = (total_paid / total_known * 100) if total_known > 0 else 0
    send_msg(chat_id,
        f"📊 *Resumen {mes_key}*\n\n"
        f"💰 Total: {fmt(total_known)}\n"
        f"✅ Pagado: {fmt(total_paid)} ({count_paid})\n"
        f"🔴 Pendiente: {fmt(total_known - total_paid)} ({count_pending})\n"
        f"📈 {pct:.0f}%"
    )

# ── MAIN — Short-polling loop ──

def main():
    if not BOT_TOKEN:
        print("=" * 60)
        print("⚠ CONFIGURAR BOT TOKEN")
        print("=" * 60)
        print()
        print("1. Abrí Telegram y buscá @BotFather")
        print("2. Enviá /newbot → elegí nombre y username")
        print("3. BotFather te da un token tipo: 123456:ABC-DEF...")
        print("4. Guardalo en: telegram_bot_token.txt")
        print()
        print("5. Mandá /start al bot y anotá tu chat_id")
        print("   Guardalo en: telegram_allowed_chats.txt")
        return

    print("💰 Gastos Mensuales — Telegram Bot")
    print("   Short-polling mode (sin python-telegram-bot)")
    print()

    # Pre-clear: break any existing long-polling connection
    print("🧹 Limpiando conexiones previas...")
    try:
        httpx.post(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
                    json={"url": "https://example.com/temp"}, timeout=5)
        time.sleep(1)
        httpx.post(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook",
                    json={"drop_pending_updates": True}, timeout=5)
        time.sleep(2)
    except Exception as e:
        logger.warning(f"Pre-clear warning: {e}")

    print("✅ Bot listo. Mandá /start desde Telegram.")
    print("   Ctrl+C para detener\n")

    last_update_id = 0
    conflict_count = 0

    while True:
        try:
            # Short-polling: no timeout, quick request/response
            r = httpx.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={"offset": last_update_id + 1, "timeout": 0, "limit": 10},
                timeout=10,
            )

            if r.status_code == 409:
                conflict_count += 1
                logger.warning(f"409 Conflict (#{conflict_count}) — otra instancia haciendo getUpdates")
                if conflict_count <= 3:
                    time.sleep(10)
                elif conflict_count <= 6:
                    logger.warning("Forzando cleanup con webhook trick...")
                    httpx.post(f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook",
                               json={"url": "https://example.com/temp"}, timeout=5)
                    time.sleep(2)
                    httpx.post(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook",
                               json={"drop_pending_updates": True}, timeout=5)
                    time.sleep(10)
                else:
                    logger.error("409 persiste — ¿Telegram Desktop abierto? ¿Otra instancia del bot?")
                    time.sleep(30)
                continue

            conflict_count = 0  # reset on success

            conflict_count = 0  # reset on success
            data = r.json()

            if not data.get("ok"):
                logger.error(f"getUpdates error: {data}")
                time.sleep(5)
                continue

            if not data.get("result"):
                time.sleep(2)  # no new messages, short-poll again in 2s
                continue

            for update in data["result"]:
                last_update_id = update["update_id"]
                msg = update.get("message")
                if not msg:
                    continue

                chat_id = msg["chat"]["id"]
                text = msg.get("text", "")

                if not text.startswith("/"):
                    continue

                parts = text.split()
                command = parts[0].lower().split("@")[0]  # strip @botname
                args = parts[1:]

                logger.info(f"cmd={command} chat={chat_id} args={args}")

                if command == "/start":
                    handle_start(chat_id)
                elif command == "/help":
                    handle_help(chat_id)
                elif command == "/pago":
                    handle_pago(chat_id, args)
                elif command == "/monto":
                    handle_monto(chat_id, args)
                elif command == "/nuevo":
                    handle_nuevo(chat_id, args)
                elif command == "/pendientes":
                    handle_pendientes(chat_id)
                elif command == "/hoy":
                    handle_hoy(chat_id)
                elif command == "/status":
                    handle_status(chat_id)

        except httpx.ReadTimeout:
            # Long-poll timeout — normal, just poll again
            continue
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        with open("bot_crash.log", "w", encoding="utf-8") as f:
            f.write(f"CRASH: {e}\n")
            f.write(traceback.format_exc())
        raise
