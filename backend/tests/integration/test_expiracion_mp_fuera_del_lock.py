"""``expire_unpaid_appointments`` no consulta a Mercado Pago con el lote bloqueado.

2026-09-16, hallazgo B2-02: el job tomaba hasta 100 turnos con ``SELECT ...
FOR UPDATE SKIP LOCKED`` y, fila por fila dentro del mismo ``for``, le pedia
el estado del cobro a Mercado Pago por HTTP (hasta 20 s por pedido) antes del
unico commit. Sintoma: con MP degradado, una corrida sostenia 100 filas de
``appointments`` bloqueadas durante minutos mientras el beat disparaba la
misma tarea cada minuto (regla 5; incidente 2026-09-04 en la reserva).

En SQLite no hay locks reales, asi que se observa el ORDEN: el HTTP a MP
tiene que ocurrir antes de la primera consulta con ``FOR UPDATE`` del job.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from modules.appointments.model import Appointment, AppointmentStatus
from modules.payments.jobs import expire_unpaid_appointments
from modules.payments.model import Payment, PaymentStatus
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _approved_remote_payment,
    _book_with_mercadopago,
    _configure_gateway,
    _enable_payments,
)


def _mercadopago_que_registra(
    monkeypatch: pytest.MonkeyPatch,
    linea_de_tiempo: list[str],
    *,
    remoto: dict[str, Any] | None,
    falla: bool = False,
) -> None:
    async def fake_request(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if path.startswith("/checkout/preferences"):
            return {
                "id": "pref-b2-02",
                "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=b202",
            }
        linea_de_tiempo.append("http")
        if falla:
            raise payments_service.MercadoPagoAPIError(
                "Mercado Pago no respondio a tiempo", transient=True
            )
        if path.startswith("/v1/payments/search"):
            return {"results": [remoto] if remoto else []}
        if path.startswith("/v1/payments/"):
            return remoto or {}
        return {}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", fake_request)


def _espiar_locks_y_commit(
    monkeypatch: pytest.MonkeyPatch,
    session: AsyncSession,
    linea_de_tiempo: list[str],
) -> None:
    """Anota cada SELECT ... FOR UPDATE y cada commit que ejecuta el job."""
    ejecutar = session.execute
    commitear = session.commit

    async def execute_espia(statement: Any, *args: Any, **kwargs: Any) -> Any:
        if getattr(statement, "_for_update_arg", None) is not None:
            linea_de_tiempo.append("lock")
        return await ejecutar(statement, *args, **kwargs)

    async def commit_espia() -> None:
        linea_de_tiempo.append("commit")
        await commitear()

    monkeypatch.setattr(session, "execute", execute_espia)
    monkeypatch.setattr(session, "commit", commit_espia)


async def _turno_vencido_con_sena_pendiente(
    client: AsyncClient, test_session: AsyncSession, *, slug: str, hour: int
) -> tuple[Appointment, Payment]:
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    await _enable_payments(client, token)
    await _configure_gateway(client, token)
    appointment_id = await _book_with_mercadopago(
        client, token, store, slug_suffix=slug, hour=hour
    )
    appointment = (
        await test_session.execute(
            select(Appointment).where(Appointment.id == appointment_id)
        )
    ).scalar_one()
    appointment.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    await test_session.commit()
    payment = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == appointment_id)
        )
    ).scalar_one()
    return appointment, payment


def _http_entre_lock_y_commit(linea_de_tiempo: list[str]) -> list[str]:
    if "lock" not in linea_de_tiempo:
        return []
    desde = linea_de_tiempo.index("lock")
    hasta = linea_de_tiempo.index("commit", desde)
    return [e for e in linea_de_tiempo[desde:hasta] if e == "http"]


@pytest.mark.asyncio
async def test_la_consulta_a_mercado_pago_va_antes_del_lock_y_el_rescate_sigue(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    linea: list[str] = []
    _mercadopago_que_registra(monkeypatch, linea, remoto=None)
    appointment, payment = await _turno_vencido_con_sena_pendiente(
        client, test_session, slug="b202-rescate", hour=10
    )
    # Ahora MP dice que ese cobro se acredito (el webhook nunca llego).
    _mercadopago_que_registra(
        monkeypatch, linea, remoto=_approved_remote_payment(payment)
    )
    _espiar_locks_y_commit(monkeypatch, test_session, linea)

    stats = await expire_unpaid_appointments(test_session)

    assert stats["rescued"] == 1 and stats["expired"] == 0, stats
    assert "http" in linea and "lock" in linea, linea
    assert _http_entre_lock_y_commit(linea) == [], (
        f"se llamo a Mercado Pago con el lote bloqueado: {linea}"
    )
    await test_session.refresh(appointment)
    await test_session.refresh(payment)
    assert appointment.status == AppointmentStatus.CONFIRMED.value
    assert payment.status == PaymentStatus.APPROVED.value


@pytest.mark.asyncio
async def test_si_mercado_pago_no_responde_el_turno_vence_sin_llamar_bajo_el_lock(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    linea: list[str] = []
    _mercadopago_que_registra(monkeypatch, linea, remoto=None)
    appointment, payment = await _turno_vencido_con_sena_pendiente(
        client, test_session, slug="b202-caido", hour=11
    )
    _mercadopago_que_registra(monkeypatch, linea, remoto=None, falla=True)
    _espiar_locks_y_commit(monkeypatch, test_session, linea)

    stats = await expire_unpaid_appointments(test_session)

    assert stats["expired"] == 1 and stats["rescued"] == 0, stats
    assert _http_entre_lock_y_commit(linea) == [], linea
    await test_session.refresh(appointment)
    await test_session.refresh(payment)
    assert appointment.status == AppointmentStatus.EXPIRED.value
    assert payment.status == PaymentStatus.EXPIRED.value
