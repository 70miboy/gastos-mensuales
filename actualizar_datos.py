"""
Script para actualizar gastos.json en GitHub directamente.
Uso: python actualizar_datos.py
"""
import json
import base64
import urllib.request
import urllib.error

GH_TOKEN = open("gh_token.txt").read().strip() if __import__("os").path.exists("gh_token.txt") else input("GitHub token: ")
GH_REPO  = "70miboy/gastos-mensuales"
GH_FILE  = "gastos.json"

def get_file():
    url = f"https://api.github.com/repos/{GH_REPO}/contents/{GH_FILE}"
    req = urllib.request.Request(url, headers={
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    })
    with urllib.request.urlopen(req) as r:
        data = json.loads(r.read())
    content = json.loads(base64.b64decode(data["content"].replace("\n","")).decode("utf-8"))
    return content, data["sha"]

def put_file(content, sha, mensaje):
    url = f"https://api.github.com/repos/{GH_REPO}/contents/{GH_FILE}"
    body = json.dumps({
        "message": mensaje,
        "content": base64.b64encode(json.dumps(content, indent=2, ensure_ascii=False).encode("utf-8")).decode(),
        "sha": sha
    }).encode()
    req = urllib.request.Request(url, data=body, method="PUT", headers={
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "Content-Type": "application/json"
    })
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

# ── Obtener contenido actual ──
print("Leyendo gastos.json desde GitHub...")
contenido, sha = get_file()

# ── Aplicar actualizaciones detectadas de los mails ──
actualizaciones = [
    {
        "mes": "2026-05",
        "id": "ormachea",
        "datos": {
            "monto": 220000,
            "fuente": "gmail:diegoormachea@hotmail.com",
            "notas": "Honorarios $220.000/mes desde Abr/2026. Confirmado mail 05/05 Diego Ormachea."
        }
    }
]

for upd in actualizaciones:
    mes = upd["mes"]
    gid = upd["id"]
    if mes not in contenido["pagos"]:
        contenido["pagos"][mes] = {}
    if gid not in contenido["pagos"][mes]:
        contenido["pagos"][mes][gid] = {"pagado": False}
    contenido["pagos"][mes][gid].update(upd["datos"])
    print(f"  Actualizado: {gid} [{mes}]")

from datetime import date
contenido["ultima_actualizacion"] = date.today().isoformat()

# ── Guardar en GitHub ──
print("Guardando en GitHub...")
put_file(contenido, sha, "Actualizar datos desde mails: Ormachea honorarios mayo 2026")
print("Listo!")
