"""Cada mail al cliente dice quien escribe, en nombre de quien y por que.

2026-09-25, L3-05 y L1 (O-7). Los mails al cliente salian firmados "El
equipo de Shifty", sin decir que la responsable del dato es la tienda, por
que llegan ni donde esta la politica de privacidad. Ahora todos cierran con
un pie comun: "Te escribimos en nombre de <tienda> a traves de Shifty", el
motivo y el link a la politica (``PUBLIC_PRIVACY_URL``; por defecto
``{FRONTEND_URL}/legal/privacidad``, la ruta real del front: ``/legal``
redirige a los terminos y la pagina no tiene anclas).

Los asuntos no ganan datos personales: se fijan tal cual estaban.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

import modules.notifications.tasks as tasks
import modules.otp.service as otp
from core.config import settings

DETALLES: dict[str, Any] = {
    "public_id": "t1",
    "client_name": "Ana",
    "service": "Corte",
    "staff": "Leo",
    "staff_kind": "person",
    "starts_at": "2026-10-01T13:00:00+00:00",
    "store_name": "Barberia Sol",
    "store_phone": "5491100000000",
    "booking_url": "https://app.example/b/sol",
    "rebook_url": "https://app.example/b/sol?service=s1",
    "block_reason": "",
    "offer_minutes": 10,
    "stage": "24h",
}

# (cuerpo, motivo que tiene que aparecer)
CUERPOS: list[tuple[str, Callable[[dict[str, Any]], str], str]] = [
    ("registro", tasks._registration_body, "reservaste un turno en Barberia Sol"),
    ("confirmacion", tasks._confirmation_body, "tenes un turno en Barberia Sol"),
    ("reprogramacion", tasks._rescheduled_body, "tenes un turno en Barberia Sol"),
    ("cancelacion", tasks._cancellation_body, "tenias un turno en Barberia Sol"),
    ("recordatorio", tasks._reminder_body, "tenes un turno en Barberia Sol"),
    ("volver", tasks._rebook_body, "tuviste un turno en Barberia Sol"),
    (
        "lista de espera",
        tasks._waitlist_offer_body,
        "te anotaste en la lista de espera de Barberia Sol",
    ),
]


def _privacidad_por_defecto() -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/legal/privacidad"


@pytest.mark.parametrize("nombre,cuerpo,motivo", CUERPOS, ids=[c[0] for c in CUERPOS])
def test_el_mail_dice_en_nombre_de_quien_por_que_y_donde_esta_la_privacidad(
    nombre: str, cuerpo: Callable[[dict[str, Any]], str], motivo: str
) -> None:
    texto = cuerpo(DETALLES)
    assert "Te escribimos en nombre de Barberia Sol a traves de Shifty" in texto
    assert f"Recibis este mail porque {motivo}" in texto
    assert _privacidad_por_defecto() in texto
    assert "El equipo de Shifty" not in texto


def test_el_link_de_privacidad_sale_de_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings, "PUBLIC_PRIVACY_URL", "https://shifty.example/privacidad"
    )
    assert "https://shifty.example/privacidad" in tasks._confirmation_body(DETALLES)


def test_sin_nombre_de_tienda_no_queda_un_hueco() -> None:
    texto = tasks._confirmation_body({**DETALLES, "store_name": ""})
    assert "Te escribimos en nombre de la tienda a traves de Shifty" in texto


def test_el_mail_del_codigo_tambien_identifica_a_la_tienda() -> None:
    for texto in (
        otp._code_body("123456", "Barberia Sol"),
        otp._notice_body("Barberia Sol"),
    ):
        assert "Te escribimos en nombre de Barberia Sol a traves de Shifty" in texto
        assert "Recibis este mail porque se pidio un codigo" in texto
        assert _privacidad_por_defecto() in texto
        assert "El equipo de Shifty" not in texto


def test_los_asuntos_no_suman_datos_personales() -> None:
    assert tasks._registration_subject(DETALLES) == "Reserva registrada - Corte"
    assert tasks._confirmation_subject(DETALLES) == "Turno confirmado - Corte"
    assert tasks._rescheduled_subject(DETALLES) == "Te movimos el turno - Corte"
    assert tasks._cancellation_subject(DETALLES) == "Turno cancelado - Corte"
    assert (
        tasks._reminder_subject(DETALLES)
        == "Recordatorio: tu turno del 01/10/2026 - Corte"
    )
    assert tasks._rebook_subject(DETALLES) == "Gracias por tu visita - Barberia Sol"
    assert (
        tasks._waitlist_offer_subject(DETALLES)
        == "Se libero un turno el 01/10/2026 a las 10:00 - Corte"
    )
    for asunto in (
        tasks._registration_subject(DETALLES),
        tasks._rebook_subject(DETALLES),
        otp._otp_subject("Barberia Sol"),
    ):
        assert "Ana" not in asunto
