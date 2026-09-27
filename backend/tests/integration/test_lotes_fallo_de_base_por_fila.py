"""Un fallo de base en una fila del lote no se lleva puesto el lote entero.

2026-09-20, AUD2-B2-11: los tres lotes (``process_outbox_batch``,
``process_webhook_inbox_batch``, ``reconcile_pending_payments``) envuelven
cada item en ``except Exception`` y siguen. Eso esta bien para un error de
Mercado Pago, pero si la excepcion venia de la BASE (``IntegrityError``,
``StaleDataError``, deadlock) la transaccion quedaba abortada: cada iteracion
siguiente fallaba, ``register_failure`` no se persistia y el ``db.commit()``
final reventaba. Resultado: se perdia el trabajo de todo el lote -- incluidos
los items que SI se habian aplicado -- y ``attempts`` no subia, asi que el
mismo lote se repetia cada minuto sin avanzar (regla 8: el intento es del
mensaje, no del lote; y el techo de B2-12 deja de funcionar si ``attempts``
nunca se persiste).

Que esas excepciones ocurren de verdad en estos caminos lo confirma S-18, que
acaba de mapear deadlock y fallo de serializacion de Postgres a 409 en el
camino HTTP.

El fallo se provoca con una colision de clave primaria, que SQLite si
verifica (a diferencia de las FK, apagadas por defecto).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.notifications.tasks as tasks
import modules.payments.jobs as jobs
from modules.notifications.model import Notification, NotificationType
from modules.payments.jobs import process_outbox_batch
from modules.payments.model import OutboxMessage
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon

CUANTOS = 3
ROMPE = 1  # indice del mensaje que hace fallar la base


def _mensaje(store_id: str, indice: int) -> OutboxMessage:
    return OutboxMessage(
        store_id=store_id,
        event_type=NotificationType.APPOINTMENT_PENDING_CONFIRMATION.value,
        payload={
            "appointment_id": f"turno-b211-{indice}",
            "client_name": f"Cliente {indice}",
            "service_name": "Corte",
        },
    )


def _notificacion_que_choca(
    monkeypatch: pytest.MonkeyPatch, *, store_id: str, id_ocupado: str
) -> None:
    """El mensaje ``ROMPE`` genera una notificacion con una PK ya usada."""
    original = jobs._build_store_notification

    def espiado(message: OutboxMessage) -> Notification | None:
        notificacion = original(message)
        payload: dict[str, Any] = dict(message.payload or {})
        if notificacion is not None and payload.get("appointment_id") == (
            f"turno-b211-{ROMPE}"
        ):
            notificacion.id = id_ocupado
        return notificacion

    monkeypatch.setattr(jobs, "_build_store_notification", espiado)
    assert store_id


@pytest.mark.asyncio
async def test_el_outbox_sigue_con_los_demas_y_le_suma_el_intento_al_que_fallo(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store_public_id, _token = await register_and_login(
        client, slug="b211-outbox", email="b211-outbox@test.com"
    )
    store_id = (
        await test_session.execute(
            select(Store.id).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    # Una notificacion previa: su id es la clave que va a chocar.
    ocupada = Notification(
        store_id=store_id,
        type=NotificationType.APPOINTMENT_PENDING_CONFIRMATION.value,
        title="Ya existe",
    )
    test_session.add(ocupada)
    mensajes = [_mensaje(store_id, i) for i in range(CUANTOS)]
    for mensaje in mensajes:
        test_session.add(mensaje)
    await test_session.commit()
    _notificacion_que_choca(monkeypatch, store_id=store_id, id_ocupado=ocupada.id)

    stats = await process_outbox_batch(test_session)

    assert stats["failed"] == 1, stats
    assert stats["processed"] == CUANTOS - 1, stats
    test_session.expire_all()
    for indice, mensaje in enumerate(mensajes):
        await test_session.refresh(mensaje)
        if indice == ROMPE:
            assert mensaje.processed_at is None, "el que fallo no puede quedar sellado"
            assert mensaje.attempts == 1, (
                "attempts no se persistio: el techo de reintentos deja de "
                "funcionar y el lote se repite cada minuto sin avanzar"
            )
            assert mensaje.error, mensaje.error
        else:
            assert mensaje.processed_at is not None, (
                "un fallo de base en OTRA fila se llevo puesto el trabajo ya "
                "aplicado de este mensaje"
            )
            assert mensaje.attempts == 0, mensaje.attempts


@pytest.mark.asyncio
async def test_la_notificacion_del_mensaje_que_fallo_no_queda_a_medias(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guarda: el savepoint revierte lo del item que fallo, no lo de los otros."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    store_public_id, _token = await register_and_login(
        client, slug="b211-parcial", email="b211-parcial@test.com"
    )
    store_id = (
        await test_session.execute(
            select(Store.id).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    ocupada = Notification(
        store_id=store_id,
        type=NotificationType.APPOINTMENT_PENDING_CONFIRMATION.value,
        title="Ya existe",
    )
    test_session.add(ocupada)
    for i in range(CUANTOS):
        test_session.add(_mensaje(store_id, i))
    await test_session.commit()
    _notificacion_que_choca(monkeypatch, store_id=store_id, id_ocupado=ocupada.id)

    await process_outbox_batch(test_session)

    test_session.expire_all()
    avisos = list(
        (
            await test_session.execute(
                select(Notification).where(
                    Notification.store_id == store_id,
                    Notification.title == "Turno pendiente de confirmar",
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(avisos) == CUANTOS - 1, [a.appointment_id for a in avisos]
    assert f"turno-b211-{ROMPE}" not in {a.appointment_id for a in avisos}
