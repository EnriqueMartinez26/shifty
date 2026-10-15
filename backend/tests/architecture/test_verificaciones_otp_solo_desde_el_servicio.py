"""``OtpVerification`` se lee y escribe solo desde ``modules/otp/service.py``.

Revision del PR #183 (2026-10-14): una verificacion OTP es la mitad en la base
de la autorizacion de la autogestion. Un modulo que consultara la tabla por su
cuenta podria volver a autorizar con "hay una verificacion reciente" sin el
token del cliente (``modules/otp/client_token.py``). Los unicos lugares que la
tocan son el servicio de OTP, el modelo, la purga de retencion y el registro
de modelos.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
CARPETAS = ("modules", "core", "scripts", "infrastructure")
PERMITIDOS = {
    "modules/otp/service.py",
    "modules/otp/model.py",
    "modules/housekeeping/retention.py",
    "core/model_registry.py",
}


def test_otp_verification_solo_desde_los_archivos_permitidos() -> None:
    usos: list[str] = []
    archivos = [BACKEND / "main.py"]
    for carpeta in CARPETAS:
        archivos.extend((BACKEND / carpeta).rglob("*.py"))
    for archivo in archivos:
        ruta = archivo.relative_to(BACKEND).as_posix()
        if ruta in PERMITIDOS:
            continue
        tree = ast.parse(archivo.read_text(encoding="utf-8"), filename=ruta)
        for nodo in ast.walk(tree):
            importa = isinstance(nodo, ast.ImportFrom) and any(
                alias.name == "OtpVerification" for alias in nodo.names
            )
            nombra = (
                isinstance(nodo, ast.Attribute) and nodo.attr == "OtpVerification"
            ) or (isinstance(nodo, ast.Name) and nodo.id == "OtpVerification")
            if importa or nombra:
                usos.append(f"{ruta}:{getattr(nodo, 'lineno', '?')}")
    assert usos == [], (
        "OtpVerification fuera del servicio de OTP: la autorizacion de la "
        f"autogestion tiene que pasar por el token del cliente. {usos}"
    )
