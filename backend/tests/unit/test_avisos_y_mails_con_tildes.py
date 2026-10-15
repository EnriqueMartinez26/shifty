"""Textos exactos de los avisos al dueño y de los mails al cliente, con tildes.

2026-10-14. Sintoma: el aviso del panel decia "Agusuto murillo pago la seña de
$100.00 ... El turno quedo confirmado automaticamente." Se corrige la
ortografia y el importe sale con ``format_ars`` ("$ 100"), como el resto de
los avisos y el panel. La guarda que impide que vuelva una palabra sin tilde
es ``tests/architecture/test_avisos_con_tildes.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from modules.notifications.model import NotificationType
from modules.notifications.tasks import (
    _confirmation_body,
    _rebook_body,
    _waitlist_offer_body,
    _waitlist_offer_subject,
    client_mail_footer,
)
from modules.otp.service import _code_body, _notice_body, _otp_subject
from modules.payments.jobs import _build_store_notification
from modules.payments.model import OutboxMessage
from modules.waitlist.offers import ReleasedSlot, _owner_notification

CLIENTE = "Agustina Murillo"
SERVICIO = "Corte"


def _aviso(evento: str, **payload: Any) -> tuple[str, str]:
    mensaje = OutboxMessage(
        store_id="tienda-1",
        event_type=evento,
        payload={"client_name": CLIENTE, "service_name": SERVICIO, **payload},
    )
    aviso = _build_store_notification(mensaje)
    assert aviso is not None
    return aviso.title, aviso.body or ""


@pytest.mark.parametrize(
    ("evento", "payload", "titulo", "cuerpo"),
    [
        (
            NotificationType.PAYMENT_APPROVED.value,
            {"amount": "100.00"},
            "Seña acreditada",
            "Agustina Murillo pagó la seña de $ 100 de Corte. "
            "El turno quedó confirmado automáticamente.",
        ),
        (
            NotificationType.APPOINTMENT_PENDING_CONFIRMATION.value,
            {},
            "Turno pendiente de confirmar",
            "Agustina Murillo reservó Corte y va a coordinar el pago. "
            "Confirmalo cuando recibas la transferencia.",
        ),
        (
            NotificationType.PAYMENT_REFUNDED.value,
            {"amount": "2500.50"},
            "Reembolso registrado",
            "Se registró un reembolso de $ 2.500,50. Shifty no mueve la plata: "
            "la devolución se hace desde Mercado Pago o en efectivo.",
        ),
        (
            NotificationType.PAYMENT_CHARGED_BACK.value,
            {"amount": "100.00"},
            "Contracargo en Mercado Pago",
            "Mercado Pago devolvió el pago de $ 100 de Agustina Murillo por "
            "Corte: esa plata ya no está en tu cuenta. El turno sigue "
            "confirmado; si no lo vas a atender, cancelalo.",
        ),
        (
            NotificationType.PAYMENT_IN_MEDIATION.value,
            {"amount": "100.00"},
            "Disputa abierta en Mercado Pago",
            "Mercado Pago abrió una disputa sobre el cobro de $ 100 de Agustina "
            "Murillo por Corte: la plata queda retenida hasta que se resuelva. "
            "El turno sigue confirmado.",
        ),
        (
            NotificationType.PAYMENT_ON_RELEASED_APPOINTMENT.value,
            {"amount": "100.00"},
            "Pago recibido de un turno ya liberado",
            "Agustina Murillo pagó la seña de $ 100 de Corte, pero el turno ya "
            "se había liberado. Devolvele la plata (registrá el reembolso) o "
            "reasignale un turno.",
        ),
        (
            NotificationType.SUBSCRIPTION_EXPIRING.value,
            {"days_left": 3, "plan_name": "Plan Pro"},
            "Tu suscripción vence pronto",
            "Plan Pro vence en 3 días. Renovala para que tu página de reservas "
            "siga funcionando.",
        ),
    ],
)
def test_el_aviso_al_dueno_lleva_tildes(
    evento: str, payload: dict[str, Any], titulo: str, cuerpo: str
) -> None:
    assert _aviso(evento, **payload) == (titulo, cuerpo)


def test_la_cancelacion_del_cliente_lleva_tildes() -> None:
    titulo, cuerpo = _aviso(NotificationType.APPOINTMENT_CANCELLED_BY_CLIENT.value)
    assert titulo == "Un cliente canceló su turno"
    assert cuerpo == (
        "Agustina Murillo canceló Corte. El horario volvió a estar disponible."
    )


def test_un_dia_de_suscripcion_va_en_singular_con_tilde() -> None:
    _titulo, cuerpo = _aviso(
        NotificationType.SUBSCRIPTION_EXPIRING.value, days_left=1, plan_name="Plan"
    )
    assert cuerpo.startswith("Plan vence en 1 día. ")


def test_el_hueco_liberado_con_gente_en_espera_lleva_tildes() -> None:
    inicio = datetime(2026, 10, 20, 15, 0, tzinfo=timezone.utc)
    aviso = _owner_notification(
        "tienda-1",
        ReleasedSlot(
            store_id="tienda-1", staff_id="p", starts_at=inicio, ends_at=inicio
        ),
        "Ana",
        2,
    )
    assert aviso.title == "Se liberó un hueco con gente en espera"
    assert (aviso.body or "").endswith(
        "Podés avisarles por WhatsApp o reservarles el turno desde Lista de espera."
    )


DETALLES: dict[str, Any] = {
    "client_name": "Agustina",
    "service": SERVICIO,
    "staff": "Ana",
    "store_name": "Barbería Norte",
    "starts_at": "2026-10-20T15:00:00+00:00",
}


def test_el_pie_de_los_mails_lleva_tildes() -> None:
    pie = client_mail_footer("Barbería Norte", "tenés un turno en Barbería Norte")
    assert "a través de Shifty" in pie
    assert "Recibís este mail porque tenés un turno en Barbería Norte." in pie
    assert "Política de privacidad:" in pie


def test_el_mail_de_confirmacion_lleva_tildes() -> None:
    cuerpo = _confirmation_body(DETALLES)
    assert "está confirmado para el 20/10/2026 a las 12:00 hs." in cuerpo


def test_el_mail_post_turno_lleva_tildes() -> None:
    cuerpo = _rebook_body(
        {**DETALLES, "rebook_url": "https://x/r", "unsubscribe_url": "https://x/b"}
    )
    assert "Reservá tu próximo turno en un toque: https://x/r" in cuerpo
    assert (
        "Si no querés recibir más estas invitaciones de Barbería Norte, podés "
        "darte de baja acá: https://x/b"
    ) in cuerpo


def test_el_mail_de_la_lista_de_espera_lleva_tildes() -> None:
    detalles = {**DETALLES, "offer_url": "https://x/o"}
    assert _waitlist_offer_subject(detalles).startswith("Se liberó un turno el ")
    cuerpo = _waitlist_offer_body(detalles)
    assert 'Se liberó un turno para "Corte"' in cuerpo
    assert "Reservalo acá: https://x/o" in cuerpo
    assert "minutos; después se lo ofrecemos" in cuerpo


def test_los_mails_del_codigo_llevan_tildes() -> None:
    assert _otp_subject("Barbería Norte") == (
        "Tu código de verificación - Barbería Norte"
    )
    codigo = _code_body("123456", "Barbería Norte")
    assert "Tu código para Barbería Norte es: 123456" in codigo
    assert "Si no pediste este código, ignorá este mensaje." in codigo
    aviso = _notice_body("Barbería Norte")
    assert "Recibimos un pedido de código de verificación" in aviso
    assert "Si el teléfono es tuyo, el código fue a la dirección" in aviso
    assert "tenés registrada. Si no reconocés este pedido, ignorá" in aviso
