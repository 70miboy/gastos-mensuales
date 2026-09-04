"""
Credenciales centralizadas para los scripts de Gastos Mensuales.

Regla: NUNCA hardcodear contraseñas en el código (este repo es público).
Cada secreto se resuelve en este orden:

  1. Variable de entorno  -> usada en producción / Fly.io:
        fly secrets set GMAIL_PASS="..."   PDF_PASSWORD="..."
  2. Archivo local .txt    -> para correr en tu máquina.
        El archivo está en .gitignore, así que nunca entra al repo.

De esta forma el secreto no vive en el código pero los scripts lo
levantan solos: no hay que pasarlo a mano cada vez.
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# El usuario no es secreto, pero se puede sobreescribir por entorno.
GMAIL_USER = os.environ.get("GMAIL_USER", "tominorman@gmail.com")


def _get_secret(env_var, filename):
    """Devuelve el secreto desde la variable de entorno o el archivo local."""
    val = os.environ.get(env_var)
    if val:
        return val.strip()

    path = os.path.join(BASE_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            secret = f.read().strip()
    except FileNotFoundError:
        raise RuntimeError(
            f"Falta el secreto '{env_var}'. Definí la variable de entorno "
            f"{env_var} o creá el archivo '{filename}' (junto a los scripts) "
            f"con el valor adentro."
        )
    if not secret:
        raise RuntimeError(
            f"El archivo '{filename}' está vacío. Pegá adentro el valor de "
            f"'{env_var}'."
        )
    return secret


def get_gmail_pass():
    """Contraseña de aplicación de Gmail (App Password)."""
    return _get_secret("GMAIL_PASS", "gmail_app_password.txt")


def get_pdf_password():
    """Contraseña para abrir los PDF de resúmenes de Credicoop."""
    return _get_secret("PDF_PASSWORD", "credicoop_pdf_password.txt")
