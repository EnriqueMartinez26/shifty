"""Ningun llamador usa la mitad en la base del gate de OTP sin el token.

Hallazgo del 2026-10-14: ``is_client_contact_verified`` y
``may_book_with_otp`` dicen que ALGUIEN verifico el OTP de (tienda, telefono)
en los ultimos 30 minutos, no que sea quien pregunta. Usados solos, cualquiera
que supiera el telefono listaba, cancelaba o reprogramaba los turnos de otra
persona durante esa ventana. El predicado que se usa es
``is_self_service_allowed`` / ``may_book`` (``modules/otp/service.py``), que
exige ademas el token de ``/public/otp/verify`` (``X-Client-Token``).

Este test falla si una llamada a los predicados solo-base aparece fuera de
``modules/otp/service.py``.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SOLO_BASE = {
    "is_client_contact_verified",
    "may_book_with_otp",
    "client_contact_verification_reason",
    "booking_otp_reason",
}
CARPETAS = ("modules", "core")
PERMITIDOS = {"modules/otp/service.py"}


def test_ningun_llamador_autoriza_solo_con_la_verificacion_en_la_base() -> None:
    llamadas: list[str] = []
    for carpeta in CARPETAS:
        for archivo in (BACKEND / carpeta).rglob("*.py"):
            ruta = archivo.relative_to(BACKEND).as_posix()
            if ruta in PERMITIDOS:
                continue
            tree = ast.parse(archivo.read_text(encoding="utf-8"), filename=ruta)
            for nodo in ast.walk(tree):
                if (
                    isinstance(nodo, ast.Call)
                    and isinstance(nodo.func, ast.Attribute)
                    and nodo.func.attr in SOLO_BASE
                ):
                    llamadas.append(f"{ruta}:{nodo.lineno} .{nodo.func.attr}(")
    assert llamadas == [], (
        "autorizacion por OTP sin el token del cliente (la verificacion de "
        f"otro abre sus datos): {llamadas}"
    )
