"""Credenciales de la base fuera de la salida de los scripts.

2026-09-16 (audit B7-04): ``run_migrations.py`` levantaba
``ValueError(f"No se pudo parsear DATABASE_URL: {url}")`` con la URL entera
(``usuario:contraseña@host``) y ``main()`` no la capturaba, asi que el
traceback con la contraseña terminaba en la consola o en el log del job de
CI. ``core/config.py`` ya redactaba exactamente ese patron para el error de
settings; el script tiene que usar la misma redaccion.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from core.config import redact_url

BACKEND_ROOT = Path(__file__).resolve().parents[2]
USUARIO = "shifty_app"
CONTRASENA = "S3cr3t-no-debe-verse"


def test_una_url_que_no_parsea_aborta_sin_imprimir_las_credenciales() -> None:
    env = dict(os.environ)
    # Esquema "postgres" (sin "ql"): urlparse lo acepta pero el script no.
    env["DATABASE_URL"] = f"postgres://{USUARIO}:{CONTRASENA}@db:5432/shifty"
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        [sys.executable, str(BACKEND_ROOT / "run_migrations.py")],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    salida = result.stdout + result.stderr

    assert result.returncode != 0
    assert "No se pudo parsear DATABASE_URL" in salida
    assert CONTRASENA not in salida
    assert USUARIO not in salida


def test_redact_url_conserva_el_esquema_y_tapa_el_resto() -> None:
    assert (
        redact_url("postgres://shifty_app:S3cr3t@db:5432/shifty?sslmode=require")
        == "postgres://[redacted]"
    )
    assert redact_url("sin url adentro") == "sin url adentro"
