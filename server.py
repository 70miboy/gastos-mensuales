"""
Servidor local para Gastos Mensuales — API REST + archivos estáticos.
Uso: python server.py
Abre http://localhost:8484/dashboard.html o http://localhost:8484/index.html
"""

import http.server
import json
import os
import shutil
import re
from datetime import date
from urllib.parse import urlparse, parse_qs

PORT = int(os.environ.get("PORT", "8484"))
DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GASTOS_FILE = os.path.join(DATA_DIR, "gastos.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
LOG_FILE = os.path.join(DATA_DIR, "check_mails_log.json")

# ── Helpers ──

def read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def write_json(path, data):
    # Backup
    bak = path + ".bak"
    if os.path.exists(path):
        shutil.copy2(path, bak)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def json_response(code, body):
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    return code, {
        "Content-Type": "application/json; charset=utf-8",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, PUT, PATCH, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }, payload

def error_response(code, msg):
    return json_response(code, {"error": msg})

# ── API Handlers ──

def api_get_gastos(params):
    data = read_json(GASTOS_FILE)
    return json_response(200, data)

def api_put_gastos(body):
    write_json(GASTOS_FILE, body)
    return json_response(200, {"ok": True, "updated": date.today().isoformat()})

def api_patch_gasto(mes, gasto_id, body):
    data = read_json(GASTOS_FILE)
    if mes not in data["pagos"]:
        data["pagos"][mes] = {}
    if gasto_id not in data["pagos"][mes]:
        data["pagos"][mes][gasto_id] = {"pagado": False}
    # Merge: solo actualizar campos presentes en el body
    for key, val in body.items():
        if val is None:
            # Permite borrar un campo
            data["pagos"][mes][gasto_id].pop(key, None)
        else:
            data["pagos"][mes][gasto_id][key] = val
    data["ultima_actualizacion"] = date.today().isoformat()
    write_json(GASTOS_FILE, data)
    return json_response(200, {"ok": True, "gasto": data["pagos"][mes][gasto_id]})

def api_post_gasto_nuevo(body):
    """Agrega un gasto nuevo a config.json y crea entrada en gastos.json para el mes actual."""
    gasto_id = body.get("id")
    if not gasto_id:
        return error_response(400, "id es requerido")

    # Validar que no exista
    config = read_json(CONFIG_FILE)
    existing_ids = [g["id"] for g in config.get("gastos_recurrentes", [])]
    if gasto_id in existing_ids:
        return error_response(409, f"Ya existe un gasto con id '{gasto_id}'")

    # Agregar a config.json
    nuevo_gasto = {
        "id": gasto_id,
        "nombre": body.get("nombre", gasto_id),
        "categoria": body.get("categoria", "servicio"),
        "persona": body.get("persona", "Tomás"),
        "gmail_busqueda": body.get("gmail_busqueda", [body.get("nombre", gasto_id)]),
        "dia_vencimiento_aprox": body.get("dia_vencimiento_aprox"),
        "activo": True
    }
    config.setdefault("gastos_recurrentes", []).append(nuevo_gasto)
    write_json(CONFIG_FILE, config)

    # Crear entrada en gastos.json para el mes actual y próximos meses
    data = read_json(GASTOS_FILE)
    mes_actual = date.today().strftime("%Y-%m")
    # También agregar al mes siguiente
    import calendar
    y, m = date.today().year, date.today().month
    if m == 12:
        mes_sig = f"{y+1}-01"
    else:
        mes_sig = f"{y}-{m+1:02d}"

    entrada = {
        "vencimiento": body.get("vencimiento"),
        "monto": body.get("monto"),
        "pagado": False,
        "pagado_fecha": None,
        "pagado_monto": None,
        "fuente": "carga_manual",
        "notas": body.get("notas", "")
    }
    # Limpiar campos None
    entrada = {k: v for k, v in entrada.items() if v is not None}

    for mes in [mes_actual, mes_sig]:
        if mes not in data["pagos"]:
            data["pagos"][mes] = {}
        if gasto_id not in data["pagos"][mes]:
            data["pagos"][mes][gasto_id] = dict(entrada)

    data["ultima_actualizacion"] = date.today().isoformat()
    write_json(GASTOS_FILE, data)

    return json_response(201, {"ok": True, "id": gasto_id})

def api_get_config(params):
    data = read_json(CONFIG_FILE)
    return json_response(200, data)

def api_put_config(body):
    write_json(CONFIG_FILE, body)
    return json_response(200, {"ok": True})

def api_get_last_check(params):
    if os.path.exists(LOG_FILE):
        data = read_json(LOG_FILE)
        return json_response(200, data)
    return json_response(200, {"last_check": None})

def api_post_check_mails(body):
    """Ejecuta el check de mails y devuelve el resultado."""
    try:
        # Importar y ejecutar check_mails
        import importlib.util
        spec = importlib.util.spec_from_file_location("check_mails",
            os.path.join(BASE_DIR, "check_mails.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.run_check()
        return json_response(200, {"ok": True, "result": result})
    except FileNotFoundError:
        return error_response(404, "check_mails.py no encontrado")
    except Exception as e:
        return error_response(500, f"Error ejecutando check_mails: {str(e)}")

# ── Router ──

ROUTES = {
    ("GET",  "/api/gastos"):          lambda params, body: api_get_gastos(params),
    ("PUT",  "/api/gastos"):          lambda params, body: api_put_gastos(body),
    ("PATCH", "/api/gasto"):          lambda params, body: api_patch_gasto(
        params.get("mes", [""])[0], params.get("id", [""])[0], body),
    ("POST", "/api/gasto-nuevo"):     lambda params, body: api_post_gasto_nuevo(body),
    ("GET",  "/api/config"):          lambda params, body: api_get_config(params),
    ("PUT",  "/api/config"):          lambda params, body: api_put_config(body),
    ("GET",  "/api/last-check"):      lambda params, body: api_get_last_check(params),
    ("POST", "/api/check-mails"):     lambda params, body: api_post_check_mails(body),
}

class GastosHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, PUT, PATCH, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)

        # API routes
        route_key = ("GET", path)
        if route_key in ROUTES:
            try:
                code, headers, payload = ROUTES[route_key](params, None)
                self.send_response(code)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(payload)
            except Exception as e:
                code, headers, payload = error_response(500, str(e))
                self.send_response(code)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(payload)
            return

        # PATCH via GET with ?_method=PATCH (fallback)
        if "_method" in params and params["_method"][0] == "PATCH":
            return self._handle_patch_from_get(params)

        # Static files
        super().do_GET()

    def _handle_patch_from_get(self, params):
        """Fallback para PATCH via GET con query params."""
        mes = params.get("mes", [""])[0]
        gasto_id = params.get("id", [""])[0]
        if not mes or not gasto_id:
            code, headers, payload = error_response(400, "mes e id requeridos")
            self.send_response(code)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(payload)
            return

        # Construir body desde params
        body = {}
        for key in ["monto", "vencimiento", "notas", "pagado", "pagado_fecha",
                     "pagado_monto", "fuente", "pago_minimo"]:
            if key in params:
                val = params[key][0]
                if key in ["monto", "pagado_monto", "pago_minimo"]:
                    body[key] = float(val) if val else None
                elif key == "pagado":
                    body[key] = val.lower() in ("true", "1", "yes")
                else:
                    body[key] = val if val else None

        try:
            code, headers, payload = api_patch_gasto(mes, gasto_id, body)
            self.send_response(code)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(payload)
        except Exception as e:
            code, headers, payload = error_response(500, str(e))
            self.send_response(code)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(payload)

    def do_PUT(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self._read_body()

        route_key = ("PUT", path)
        if route_key in ROUTES:
            try:
                code, headers, payload = ROUTES[route_key]({}, body)
            except Exception as e:
                code, headers, payload = error_response(500, str(e))
            self.send_response(code)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_error(404)

    def do_PATCH(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        params = parse_qs(parsed.query)
        body = self._read_body()

        # /api/gasto/{mes}/{id}
        match = re.match(r"^/api/gasto/([^/]+)/([^/]+)$", path)
        if match:
            mes, gasto_id = match.group(1), match.group(2)
            try:
                code, headers, payload = api_patch_gasto(mes, gasto_id, body)
            except Exception as e:
                code, headers, payload = error_response(500, str(e))
            self.send_response(code)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(payload)
            return

        # Fallback: query params
        route_key = ("PATCH", path)
        if route_key in ROUTES:
            try:
                code, headers, payload = ROUTES[route_key](params, body)
            except Exception as e:
                code, headers, payload = error_response(500, str(e))
            self.send_response(code)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self._read_body()

        route_key = ("POST", path)
        if route_key in ROUTES:
            try:
                code, headers, payload = ROUTES[route_key]({}, body)
            except Exception as e:
                code, headers, payload = error_response(500, str(e))
            self.send_response(code)
            for k, v in headers.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(payload)
            return

        self.send_error(404)

    def _read_body(self):
        content_length = int(self.headers.get("Content-Length", 0))
        if content_length == 0:
            return {}
        raw = self.rfile.read(content_length)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    def end_headers(self):
        # Cache busting para JSON
        if self.path.endswith(".json"):
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()

    def log_message(self, format, *args):
        # Quieter logs — solo mostrar API calls y errores
        msg = format % args
        if "/api/" in msg or "404" in msg or "500" in msg:
            super().log_message(format, *args)


if __name__ == "__main__":
    print(f"💰 Gastos Mensuales — Servidor local")
    print(f"   Dashboard: http://localhost:{PORT}/dashboard.html")
    print(f"   Mobile:    http://localhost:{PORT}/index.html")
    print(f"   API:       http://localhost:{PORT}/api/gastos")
    print(f"   Ctrl+C para detener\n")
    with http.server.HTTPServer(("", PORT), GastosHandler) as httpd:
        httpd.serve_forever()
