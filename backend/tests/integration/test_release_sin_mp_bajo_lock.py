"""Liberar un turno no llama a Mercado Pago bajo lock: lo hace el outbox despues.

Audit B1-04 (2026-09-18), regla 5 de CLAUDE.md. Sintoma: ``release_pending``
hacia el ``PUT /checkout/preferences/{id}`` de Mercado Pago entre el
``SELECT ... FOR UPDATE`` del turno y del pago y el commit: con MP lento cada
liberacion retenia una conexion y los locks (el incidente de 2026-09-04), y
con MP caido el turno directamente no se liberaba (502).

Decision (OK global del usuario, sugerencia del brief): el turno se libera ya
(commit) y el vencimiento del link queda como reintento best-effort desde el
outbox. ``release_pending`` publica ``payment.preference.expire`` en la misma
transaccion; ``process_outbox_batch`` lo reclama bajo su lote, commitea y
recien entonces llama a MP, sin lock ni transaccion abierta, y anota el
resultado en una transaccion nueva. El reclamo vence (lease): si el worker
muere a mitad, otra corrida lo retoma.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.service as payments_service
from modules.appointments.model import Appointment
from core.utils import ensure_utc_aware
from modules.payments.jobs import (
    MP_REQUEST_TIMEOUT,
    PREFERENCE_EXPIRE_CLAIM,
    PREFERENCE_EXPIRE_LEASE,
    PREFERENCE_EXPIRE_MARGIN,
    PREFERENCE_EXPIRE_MAX_CLAIMS,
    PREFERENCE_EXPIRE_WORST_CASE_PER_CLAIM,
    process_outbox_batch,
)
from modules.payments.model import OutboxMessage, Payment
from modules.payments.service import EVENT_PREFERENCE_EXPIRE
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


class _MercadoPago:
    """Doble de la API: crea preferencias y registra cada vencimiento."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.vencimientos: list[bool] = []  # en_transaccion al momento del PUT
        self.falla = False
        self.eventos: list[str] | None = None

    async def __call__(
        self,
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert access_token
        if method == "POST":
            return {
                "id": "pref-release-b104",
                "sandbox_init_point": "https://sandbox.mercadopago.com/x?pref=b104",
            }
        assert method == "PUT"
        assert path == "/checkout/preferences/pref-release-b104"
        assert json_body and json_body["expires"] is True
        self.vencimientos.append(self.session.in_transaction())
        if self.eventos is not None:
            self.eventos.append("mp")
        if self.falla:
            raise RuntimeError("mercado pago caido")
        return {"id": "pref-release-b104", "expires": True}


async def _turno_con_cobro(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, mp: _MercadoPago, slug: str
) -> tuple[str, str]:
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    flags = await client.put(
        "/stores/me/feature-flags", headers=auth_headers(token), json={"payments": True}
    )
    assert flags.status_code == 200, flags.text
    gateway = await client.put(
        "/payments/gateway-config",
        headers=auth_headers(token),
        json={"access_token": "TEST-RELEASE-B104-TOKEN"},
    )
    assert gateway.status_code == 200, gateway.text
    service = await create_service(
        client,
        token,
        deposit_mode="required",
        deposit_type="fixed",
        deposit_amount=2500,
    )
    staff = await create_staff(client, token, service)
    dia = datetime.now(timezone.utc) + timedelta(days=3)
    await add_staff_schedule(client, token, staff, target_date=dia)
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": service,
            "staff_id": staff,
            "starts_at": dia.replace(
                hour=12, minute=0, second=0, microsecond=0
            ).isoformat(),
            "client_name": "Cliente Release",
            "client_phone": "+5491155556001",
            "payment_method": "mercadopago",
            "idempotency_key": f"{slug}-reserva-0001",
        },
    )
    assert reserva.status_code == 201, reserva.text
    assert reserva.json()["status"] == "pending_payment"
    return token, str(reserva.json()["public_id"])


async def _evento(session: AsyncSession) -> OutboxMessage:
    session.expire_all()
    return (
        await session.execute(
            select(OutboxMessage).where(
                OutboxMessage.event_type == EVENT_PREFERENCE_EXPIRE
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_liberar_no_llama_a_mp_y_publica_el_vencimiento(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    mp = _MercadoPago(test_session)
    token, turno = await _turno_con_cobro(client, monkeypatch, mp, "release-orden")

    liberado = await client.patch(
        f"/appointments/{turno}/release", headers=auth_headers(token)
    )

    assert liberado.status_code == 200, liberado.text
    assert liberado.json()["status"] == "expired"
    # Regla 5: ninguna llamada externa en el request que sostiene los locks.
    assert mp.vencimientos == []
    evento = await _evento(test_session)
    assert evento.processed_at is None
    assert evento.payload["preference_id"] == "pref-release-b104"
    assert evento.payload["appointment_id"] == turno
    pago = (
        await test_session.execute(
            select(Payment).where(Payment.appointment_id == turno)
        )
    ).scalar_one()
    assert pago.status == "expired"


@pytest.mark.asyncio
async def test_el_consumidor_llama_a_mp_despues_del_commit_y_sin_transaccion(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    mp = _MercadoPago(test_session)
    token, turno = await _turno_con_cobro(client, monkeypatch, mp, "release-consumo")
    liberado = await client.patch(
        f"/appointments/{turno}/release", headers=auth_headers(token)
    )
    assert liberado.status_code == 200, liberado.text

    eventos: list[str] = []
    mp.eventos = eventos
    commit_original = test_session.commit

    async def commit_espiado() -> None:
        eventos.append("commit")
        await commit_original()

    monkeypatch.setattr(test_session, "commit", commit_espiado)
    resultado = await process_outbox_batch(test_session)
    monkeypatch.undo()
    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp)

    assert mp.vencimientos == [False], "el PUT a MP corrio con una transaccion abierta"
    assert eventos.index("commit") < eventos.index("mp"), eventos
    assert resultado["failed"] == 0, resultado
    evento = await _evento(test_session)
    assert evento.processed_at is not None and evento.error is None
    # El resto del outbox se proceso igual (el aviso de liberacion, el cupo).
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


@pytest.mark.asyncio
async def test_con_mp_caido_el_turno_queda_liberado_y_el_vencimiento_se_reintenta(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    mp = _MercadoPago(test_session)
    mp.falla = True
    token, turno = await _turno_con_cobro(client, monkeypatch, mp, "release-caido")

    liberado = await client.patch(
        f"/appointments/{turno}/release", headers=auth_headers(token)
    )
    # Antes: 502 PAYMENT_PREFERENCE_EXPIRATION_FAILED y el turno retenido.
    assert liberado.status_code == 200, liberado.text
    estado = (
        await test_session.execute(select(Appointment).where(Appointment.id == turno))
    ).scalar_one()
    assert estado.status == "expired"

    fallida = await process_outbox_batch(test_session)
    assert fallida["failed"] == 1, fallida
    evento = await _evento(test_session)
    assert evento.processed_at is None, "un fallo tiene que quedar para reintento"
    assert evento.attempts == 1
    assert evento.error and evento.error != PREFERENCE_EXPIRE_CLAIM

    mp.falla = False
    await process_outbox_batch(test_session)
    evento = await _evento(test_session)
    assert evento.processed_at is not None and evento.error is None
    assert mp.vencimientos == [False, False]


@pytest.mark.asyncio
async def test_un_reclamo_con_lease_vencido_se_retoma_y_llama_a_mp_una_vez(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El worker murio entre el commit del reclamo y el resultado."""
    mp = _MercadoPago(test_session)
    token, turno = await _turno_con_cobro(client, monkeypatch, mp, "release-lease")
    liberado = await client.patch(
        f"/appointments/{turno}/release", headers=auth_headers(token)
    )
    assert liberado.status_code == 200, liberado.text
    # Todo lo demas del outbox, procesado; el vencimiento queda reclamado por
    # una corrida que "murio" hace mas que el lease.
    for mensaje in (await test_session.execute(select(OutboxMessage))).scalars():
        mensaje.processed_at = datetime.now(timezone.utc)
    evento = await _evento(test_session)
    evento.error = PREFERENCE_EXPIRE_CLAIM
    evento.processed_at = datetime.now(timezone.utc) - PREFERENCE_EXPIRE_LEASE * 2
    await test_session.commit()

    await process_outbox_batch(test_session)

    assert mp.vencimientos == [False], mp.vencimientos
    evento = await _evento(test_session)
    assert evento.processed_at is not None and evento.error is None
    # Otra corrida no lo vuelve a tomar: ya no esta reclamado.
    await process_outbox_batch(test_session)
    assert mp.vencimientos == [False]


@pytest.mark.asyncio
async def test_un_reclamo_vigente_no_se_toca(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Otra corrida lo tiene en vuelo: no se llama a MP dos veces."""
    mp = _MercadoPago(test_session)
    token, turno = await _turno_con_cobro(client, monkeypatch, mp, "release-vigente")
    liberado = await client.patch(
        f"/appointments/{turno}/release", headers=auth_headers(token)
    )
    assert liberado.status_code == 200, liberado.text
    evento = await _evento(test_session)
    evento.error = PREFERENCE_EXPIRE_CLAIM
    evento.processed_at = datetime.now(timezone.utc)
    await test_session.commit()

    await process_outbox_batch(test_session)

    assert mp.vencimientos == []
    evento = await _evento(test_session)
    assert evento.error == PREFERENCE_EXPIRE_CLAIM


# ---------------------------------------------------------------------------
# Revision V-diff de B1-04 (2026-09-19)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_los_lotes_del_outbox_no_usan_or_y_el_principal_usa_el_indice(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Un ``OR`` en el lote rompia el indice parcial ``ix_outbox_pending``
    (``WHERE processed_at IS NULL``) y la rama de reclamos arrastraba todo el
    historico del evento: seq scan cada minuto. Ahora el lote principal
    excluye los vencimientos de MP (predicado extra sobre el indice) y el
    paso de vencimientos hace dos consultas propias, cada una con su tope."""
    from sqlalchemy import text
    from sqlalchemy.dialects import sqlite

    mp = _MercadoPago(test_session)
    token, turno = await _turno_con_cobro(client, monkeypatch, mp, "release-plan")
    liberado = await client.patch(
        f"/appointments/{turno}/release", headers=auth_headers(token)
    )
    assert liberado.status_code == 200, liberado.text

    lotes: list[Any] = []
    original = test_session.execute

    async def execute_espiado(statement: Any, *args: Any, **kwargs: Any) -> Any:
        sql = str(statement)
        # Solo los lotes (con LIMIT); la relectura por id del resultado no.
        if "FROM outbox_messages" in sql and "FOR UPDATE" in sql and "LIMIT" in sql:
            lotes.append(statement)
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(test_session, "execute", execute_espiado)
    await process_outbox_batch(test_session)
    monkeypatch.undo()

    textos = [str(s) for s in lotes]
    assert len(textos) == 3, textos
    assert all(" OR " not in t for t in textos), textos
    principal = next(s for s, t in zip(lotes, textos) if "event_type !=" in t)
    assert "processed_at IS NULL" in str(principal)
    assert any("outbox_messages.error =" in t for t in textos), textos

    # El indice parcial de la migracion (a1c3e5f7b9d0), recreado aca: SQLite
    # tambien usa un indice parcial solo si el WHERE lo implica.
    await test_session.execute(
        text(
            "CREATE INDEX ix_outbox_pending ON outbox_messages (created_at) "
            "WHERE processed_at IS NULL"
        )
    )
    compilado = principal.compile(
        dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}
    )
    plan = (await test_session.execute(text(f"EXPLAIN QUERY PLAN {compilado}"))).all()
    assert any("ix_outbox_pending" in str(fila) for fila in plan), plan


@pytest.mark.asyncio
async def test_el_resultado_no_pisa_un_reclamo_que_retomo_otra_corrida(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``db.get`` devolvia la instancia en memoria (expire_on_commit=False):
    el control "sigue siendo mi reclamo" nunca veia que otra corrida lo habia
    retomado y le pisaba el reclamo. Se relee de la base con lock."""
    from sqlalchemy import update

    mp = _MercadoPago(test_session)
    token, turno = await _turno_con_cobro(client, monkeypatch, mp, "release-ajeno")
    liberado = await client.patch(
        f"/appointments/{turno}/release", headers=auth_headers(token)
    )
    assert liberado.status_code == 200, liberado.text
    evento_id = (await _evento(test_session)).id
    de_otra_corrida = datetime(2030, 1, 1, tzinfo=timezone.utc)

    llamada_original = mp.__call__

    async def mp_mientras_otra_corrida_retoma(*args: Any, **kwargs: Any) -> Any:
        respuesta = await llamada_original(*args, **kwargs)
        if kwargs.get("method") == "PUT":
            # Otra corrida retomo el reclamo (lease vencido) mientras esta
            # hablaba con MP: la fila ya no es de esta corrida.
            await test_session.execute(
                update(OutboxMessage)
                .where(OutboxMessage.id == evento_id)
                .values(processed_at=de_otra_corrida, error=PREFERENCE_EXPIRE_CLAIM)
                .execution_options(synchronize_session=False)
            )
            await AsyncSession.commit(test_session)
        return respuesta

    monkeypatch.setattr(
        payments_service, "_mercadopago_api_request", mp_mientras_otra_corrida_retoma
    )
    await process_outbox_batch(test_session)

    evento = await _evento(test_session)
    assert evento.error == PREFERENCE_EXPIRE_CLAIM, "se piso el reclamo ajeno"
    assert evento.processed_at is not None
    assert ensure_utc_aware(evento.processed_at) == de_otra_corrida


@pytest.mark.asyncio
async def test_una_corrida_toma_como_mucho_el_tope_de_reclamos(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con el tope, el peor caso de una corrida entra en el lease."""
    mp = _MercadoPago(test_session)
    token, turno = await _turno_con_cobro(client, monkeypatch, mp, "release-tope")
    liberado = await client.patch(
        f"/appointments/{turno}/release", headers=auth_headers(token)
    )
    assert liberado.status_code == 200, liberado.text
    original = await _evento(test_session)
    for _ in range(PREFERENCE_EXPIRE_MAX_CLAIMS + 1):
        test_session.add(
            OutboxMessage(
                store_id=original.store_id,
                event_type=EVENT_PREFERENCE_EXPIRE,
                payload=dict(original.payload),
            )
        )
    await test_session.commit()

    await process_outbox_batch(test_session)

    assert len(mp.vencimientos) == PREFERENCE_EXPIRE_MAX_CLAIMS
    test_session.expire_all()
    quedan = (
        (
            await test_session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.event_type == EVENT_PREFERENCE_EXPIRE,
                    OutboxMessage.processed_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(quedan) == 2, "lo que no entra espera a la corrida siguiente"


def test_el_peor_caso_de_una_corrida_entra_en_el_lease() -> None:
    """``reclamos x peor caso por reclamo + margen < lease``.

    Si una corrida pudiera tardar mas que el lease, otra retomaria reclamos
    todavia en vuelo. El peor caso por reclamo cuenta el reintento OAuth
    (PUT con 401, refresh del token, PUT de nuevo) con el timeout de httpx
    de cada request a MP.
    """
    assert (
        PREFERENCE_EXPIRE_MAX_CLAIMS * PREFERENCE_EXPIRE_WORST_CASE_PER_CLAIM
        + PREFERENCE_EXPIRE_MARGIN
        < PREFERENCE_EXPIRE_LEASE
    )


def test_el_timeout_supuesto_es_el_de_los_clientes_http_de_mp() -> None:
    """Si alguien sube el timeout de httpx, la cuenta del lease queda vieja."""
    import inspect

    fuente = inspect.getsource(payments_service)
    segundos = MP_REQUEST_TIMEOUT.total_seconds()
    assert fuente.count("timeout=") == fuente.count(f"timeout={segundos}"), (
        "un cliente HTTP de MP usa otro timeout que MP_REQUEST_TIMEOUT"
    )


@pytest.mark.asyncio
async def test_con_mp_lento_los_mails_del_lote_salen_antes_que_mp(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Los mails del lote comun no esperan a Mercado Pago (revision B1-04)."""
    import asyncio

    import modules.notifications.tasks as tasks
    from modules.notifications.model import NotificationType

    mp = _MercadoPago(test_session)
    token, turno = await _turno_con_cobro(client, monkeypatch, mp, "release-mails")
    liberado = await client.patch(
        f"/appointments/{turno}/release", headers=auth_headers(token)
    )
    assert liberado.status_code == 200, liberado.text
    evento = await _evento(test_session)
    # Un aviso al duenio en el mismo lote: genera un mail.
    test_session.add(
        OutboxMessage(
            store_id=evento.store_id,
            event_type=NotificationType.APPOINTMENT_PENDING_CONFIRMATION.value,
            payload={"appointment_id": turno, "client_name": "Cliente Release"},
        )
    )
    await test_session.commit()

    orden: list[str] = []
    mp.eventos = orden
    llamada = mp.__call__

    async def mp_lento(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("method") == "PUT":
            await asyncio.sleep(0.2)
        return await llamada(*args, **kwargs)

    async def enviar(to: str, subject: str, body: str) -> bool:
        orden.append("mail")
        return True

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mp_lento)
    monkeypatch.setattr(tasks, "_send_email", enviar)

    await process_outbox_batch(test_session)

    assert "mail" in orden and "mp" in orden, orden
    assert orden.index("mp") > max(i for i, e in enumerate(orden) if e == "mail"), orden
