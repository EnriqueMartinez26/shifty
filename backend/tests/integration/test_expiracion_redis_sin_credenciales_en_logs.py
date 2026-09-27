"""El vencimiento de senas loguea un Redis caido por su tipo, no por su texto.

PV-22, resto que encontro la revision (2026-09-24): ``expire_unpaid_appointments``
atrapaba el Redis de cache caido al invalidar la disponibilidad y logueaba
``error=str(exc)``. El texto de un error de conexion de redis-py puede repetir
la URL de conexion con la clave.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

import modules.notifications.tasks as tasks
import modules.payments.jobs as jobs
from modules.payments.jobs import expire_unpaid_appointments
from tests.integration.test_expiracion_mp_fuera_del_lock import (
    _mercadopago_que_registra,
    _turno_vencido_con_sena_pendiente,
)
from tests.integration.test_mails_al_cliente import Buzon

_SECRETO = "clave-de-redis-super-secreta"


@pytest.mark.asyncio
async def test_el_redis_caido_del_vencimiento_no_filtra_la_url(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _mercadopago_que_registra(monkeypatch, [], remoto=None)
    await _turno_vencido_con_sena_pendiente(
        client, test_session, slug="pv22-venc", hour=10
    )

    async def cache_caido() -> None:
        raise RedisConnectionError(
            f"Error connecting to redis://:{_SECRETO}@redis-cache:6379/0."
        )

    monkeypatch.setattr(jobs, "get_availability_cache", cache_caido)

    with capture_logs() as eventos:
        stats = await expire_unpaid_appointments(test_session)

    assert stats["expired"] == 1, stats
    fallos = [
        e for e in eventos if e["event"] == "availability_cache_invalidation_failed"
    ]
    assert len(fallos) == 1
    assert fallos[0]["error_type"] == "ConnectionError"
    assert _SECRETO not in str(fallos[0])
