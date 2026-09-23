"""V-diff de AUD2-B4-02 (2026-09-20): el despacho corria con una transaccion idle.

Sintoma: ``process_outbox_batch`` commiteaba el lote con ``db.commit()``, y la
sesion de los jobs (y la de ``get_db``) es ``TenantSession``, cuyo ``commit()``
reaplica el contexto de tenant. Con autobegin, ese ``set_config`` abre una
transaccion nueva que queda IDLE durante todo ``_dispatch_pending_emails``:
la misma trampa que S-02 documenta en ``_expire_unpaid_appointments``. El rol
de la app tiene ``idle_in_transaction_session_timeout`` (migracion
``app_role_timeouts``) y el presupuesto del despacho era de 90 s: un despacho
de 60-90 s hacia que Postgres matara la conexion, el commit de los fallados
reventaba y los fallos NO quedaban anotados. Lo no enviado se perdia sin la
huella que AUD2-B4-02 vino a dejar.

Se prueba con una ``TenantSession`` de verdad sobre el motor de tests: en
SQLite ``_apply_tenant_context`` no ejecuta ``set_config``, pero
``session.connection()`` ya abre la transaccion, asi que ``in_transaction()``
la delata igual.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.payments.jobs as jobs
from core.database import TenantSession
from modules.payments.model import OutboxMessage
from tests.integration.test_outbox_sesion_smtp_y_presupuesto import _mensajes

_MIGRACION_TIMEOUTS = next(
    Path(__file__).resolve().parents[2].glob("alembic/versions/*app_role_timeouts*.py")
)


def _timeout_idle_del_rol() -> int:
    """Segundos de ``idle_in_transaction_session_timeout`` del rol, del SQL real."""
    fuente = _MIGRACION_TIMEOUTS.read_text(encoding="utf-8")
    encontrado = re.search(
        r"idle_in_transaction_session_timeout\s*=\s*'(\d+)s'", fuente
    )
    assert encontrado, "la migracion app_role_timeouts ya no fija el timeout idle"
    return int(encontrado.group(1))


@pytest.mark.asyncio
async def test_entre_el_commit_del_lote_y_los_envios_no_hay_transaccion_abierta(
    test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    sesiones = async_sessionmaker(
        bind=test_engine,
        class_=TenantSession,
        expire_on_commit=False,
        autoflush=False,
    )
    abierta_al_conectar: list[bool] = []
    abierta_al_mandar: list[bool] = []

    async with sesiones() as db:
        mensajes = _mensajes(3)
        for mensaje in mensajes:
            db.add(mensaje)
        await db.commit()

        @asynccontextmanager
        async def smtp_espia() -> AsyncIterator[object]:
            abierta_al_conectar.append(db.in_transaction())
            yield object()

        async def envio(
            *, email: str | None, details: dict[str, Any], smtp: Any = None
        ) -> dict[str, str]:
            abierta_al_mandar.append(db.in_transaction())
            if email == "cliente-1@example.com":
                raise ConnectionRefusedError("smtp caido")
            return {"status": "sent", "to": str(email)}

        monkeypatch.setattr(jobs, "smtp_session", smtp_espia)
        monkeypatch.setattr(jobs, "send_cancellation_email", envio)

        resultado = await jobs.process_outbox_batch(db)

    assert resultado["processed"] == 3
    # Regla 5: ningun envio corre con una transaccion abierta, ni siquiera
    # una idle que TenantSession.commit() abre al reaplicar el contexto.
    assert abierta_al_conectar == [False], "la sesion SMTP se abrio en transaccion"
    assert abierta_al_mandar == [False, False, False], abierta_al_mandar

    # El fallo queda anotado de verdad (otra sesion: solo ve lo commiteado).
    async with AsyncSession(test_engine) as otra:
        fila = await otra.scalar(
            select(OutboxMessage).where(OutboxMessage.id == mensajes[1].id)
        )
    assert fila is not None
    assert fila.attempts == 1
    assert fila.error == "ConnectionRefusedError"
    assert fila.processed_at is not None


def test_el_presupuesto_del_despacho_queda_por_debajo_del_timeout_idle_del_rol() -> (
    None
):
    """Con margen: el presupuesto se revisa ANTES de cada envio, y el envio
    en curso puede sumar hasta el timeout del SMTP (10 s)."""
    timeout_idle = _timeout_idle_del_rol()
    assert jobs.OUTBOX_EMAIL_BUDGET_SECONDS + 10 < timeout_idle, (
        f"presupuesto {jobs.OUTBOX_EMAIL_BUDGET_SECONDS}s + 10 s de SMTP contra "
        f"idle_in_transaction_session_timeout={timeout_idle}s: Postgres mata la "
        "conexion antes de anotar los fallos"
    )
