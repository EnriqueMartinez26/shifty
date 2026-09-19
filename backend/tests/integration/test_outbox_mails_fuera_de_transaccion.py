"""El lote del outbox no manda mails dentro de su transaccion (audit B2-01).

2026-09-16, hallazgo B2-01: ``process_outbox_batch`` tomaba las filas con
``FOR UPDATE SKIP LOCKED`` y, antes del unico commit, mandaba por SMTP el aviso
al dueno, la confirmacion al cliente y el mail de cancelacion por bloqueo. Solo
las ofertas de lista de espera se diferian. Sintoma: si Celery mata la tarea a
mitad del lote, los ``processed_at`` ya asignados se pierden con el rollback y
la corrida siguiente vuelve a mandar los mails que ya salieron.

Regla (CLAUDE.md, Fases 4-7): el lote commitea una sola vez y el mail se
despacha DESPUES del commit, como ``OfferResult.pending_email``.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.jobs as payments_jobs
from modules.notifications.model import NotificationType
from modules.payments.jobs import process_outbox_batch
from modules.payments.model import OutboxMessage, Payment
from modules.payments.processing import apply_mercadopago_webhook_payload
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import (
    _approved_remote_payment,
    _book_with_mercadopago,
    _configure_gateway,
    _enable_payments,
    _stub_mercadopago,
)


class ProcesoMuerto(BaseException):
    """Simula el time limit duro de Celery: el proceso muere sin commitear."""


async def _tienda_manual(
    client: AsyncClient, slug: str
) -> tuple[str, str, str, str, datetime]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@example.com")
    dia = datetime.now(timezone.utc) + timedelta(days=4)
    await add_staff_schedule(client, token, staff, target_date=dia)
    return (
        store,
        token,
        service,
        staff,
        dia.replace(hour=13, minute=0, second=0, microsecond=0),
    )


async def _reserva_manual(
    client: AsyncClient,
    store: str,
    service: str,
    staff: str,
    cuando: datetime,
    *,
    nombre: str,
    key: str,
) -> str:
    res = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": cuando.isoformat(),
            "client_name": nombre,
            "client_phone": f"+54911555{abs(hash(key)) % 10000:04d}",
            "client_email": f"{key}@example.com",
            "payment_method": "manual",
            "accepts_terms": True,
            "idempotency_key": key,
        },
    )
    assert res.status_code == 201, res.text
    return str(res.json()["public_id"])


async def _processed_at_en_base(
    session: AsyncSession, event_type: str
) -> list[datetime | None]:
    """Lo que la BASE tiene persistido para ese evento, no el objeto en memoria."""
    rows = await session.execute(
        select(OutboxMessage.processed_at).where(OutboxMessage.event_type == event_type)
    )
    return list(rows.scalars().all())


@pytest.mark.asyncio
async def test_los_tres_mails_del_lote_salen_con_el_evento_ya_commiteado(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Aviso al dueno, confirmacion al cliente y cancelacion por bloqueo: los
    tres se mandan cuando ``processed_at`` ya esta en la base."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _stub_mercadopago(monkeypatch, remote_payment=None)
    store, token, service, staff, cuando = await _tienda_manual(client, "outbox-txn")
    await _enable_payments(client, token)
    await _configure_gateway(client, token)

    # 1) Reserva manual -> aviso al dueno (appointment.pending_confirmation).
    await _reserva_manual(
        client, store, service, staff, cuando, nombre="Cliente Uno", key="outbox-txn-1"
    )
    # 2) Bloqueo que cancela ese turno -> mail de cancelacion al cliente.
    bloqueo = await client.post(
        "/appointment-blocks/batch",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": cuando.isoformat(),
            "ends_at": (cuando + timedelta(hours=1)).isoformat(),
            "reason": "Corte de luz",
            "recurrence": "none",
            "cancel_affected": True,
        },
    )
    assert bloqueo.status_code == 201, bloqueo.text
    # 3) Sena acreditada -> confirmacion al cliente (payment.approved).
    pagado = await _book_with_mercadopago(
        client, token, store, slug_suffix="outbox-txn", hour=16
    )
    payment = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == pagado)
        )
    ).scalar_one()
    remoto = _approved_remote_payment(payment)
    assert await apply_mercadopago_webhook_payload(
        test_session,
        store_id=payment.store_id,
        payload={"data": remoto, "status": remoto["status"]},
    )
    await test_session.commit()

    vistos: dict[str, list[datetime | None]] = {}

    async def dueno(
        *, email: str, title: str, body: str | None = None
    ) -> dict[str, str]:
        vistos["dueno"] = await _processed_at_en_base(
            test_session, NotificationType.APPOINTMENT_PENDING_CONFIRMATION.value
        )
        return {"status": "sent"}

    async def cancelacion(
        *, email: str | None, details: dict[str, Any]
    ) -> dict[str, str]:
        vistos["cancelacion"] = await _processed_at_en_base(
            test_session, "appointment.cancelled_by_block"
        )
        return {"status": "sent"}

    async def confirmacion(
        *, email: str | None, details: dict[str, Any]
    ) -> dict[str, str]:
        vistos["confirmacion"] = await _processed_at_en_base(
            test_session, NotificationType.PAYMENT_APPROVED.value
        )
        return {"status": "sent"}

    monkeypatch.setattr(payments_jobs, "send_store_notification_email", dueno)
    monkeypatch.setattr(payments_jobs, "send_cancellation_email", cancelacion)
    monkeypatch.setattr(payments_jobs, "send_confirmation_email", confirmacion)

    stats = await process_outbox_batch(test_session)
    assert stats["failed"] == 0, stats

    assert set(vistos) == {"dueno", "cancelacion", "confirmacion"}, vistos
    for camino, marcas in vistos.items():
        assert marcas and all(m is not None for m in marcas), (
            f"el mail de {camino} salio con el evento todavia sin commitear"
        )


@pytest.mark.asyncio
async def test_un_corte_durante_los_envios_no_reenvia_lo_ya_enviado(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Celery mata la tarea en el segundo mail: el primero no se manda dos veces."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store, token, service, staff, cuando = await _tienda_manual(client, "outbox-corte")
    await _reserva_manual(
        client,
        store,
        service,
        staff,
        cuando,
        nombre="Cliente Uno",
        key="outbox-corte-1",
    )
    await _reserva_manual(
        client,
        store,
        service,
        staff,
        cuando + timedelta(hours=1),
        nombre="Cliente Dos",
        key="outbox-corte-2",
    )

    enviados: list[str] = []
    matar_en_el_segundo = True

    async def dueno(
        *, email: str, title: str, body: str | None = None
    ) -> dict[str, str]:
        if matar_en_el_segundo and enviados:
            raise ProcesoMuerto()
        enviados.append(body or "")
        return {"status": "sent"}

    monkeypatch.setattr(payments_jobs, "send_store_notification_email", dueno)

    with pytest.raises(ProcesoMuerto):
        await process_outbox_batch(test_session)
    # El proceso murio: nada que no haya commiteado sobrevive.
    await test_session.rollback()

    matar_en_el_segundo = False
    await process_outbox_batch(test_session)

    de_uno = [cuerpo for cuerpo in enviados if "Cliente Uno" in cuerpo]
    assert len(de_uno) == 1, f"el mail ya enviado se volvio a mandar: {enviados}"
    pendientes = (
        (
            await test_session.execute(
                select(OutboxMessage).where(OutboxMessage.processed_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    assert pendientes == []
