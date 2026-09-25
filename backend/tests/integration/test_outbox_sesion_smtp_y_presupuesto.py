"""AUD2-B4-02 (2026-09-20): el lote del outbox manda con UNA conexion SMTP.

Sintoma: ``process_outbox_batch`` commitea una sola vez y despues despacha la
lista de mails (correcto, B2-01), pero cada ``send_*_email`` abria su PROPIA
conexion + STARTTLS + LOGIN. El lote trae hasta 100 mensajes, cada mensaje
puede generar varios mails (uno por administrador de la tienda mas la
confirmacion al cliente), corre por beat cada minuto y esta bajo el time limit
de Celery (120 s soft / 150 s hard). Con un SMTP lento el hard limit mataba el
proceso DESPUES del commit: los ``processed_at`` ya estaban persistidos y los
mails que faltaban no salian nunca, sin ningun rastro. El mismo camino se
expone por HTTP con ``limit`` hasta 500 (``/payments/outbox/process``).

Correccion (decision del coordinador): una sesion SMTP por lote, como el lote
de recordatorios desde B4-08; presupuesto de tiempo para el despacho; y lo que
no sale queda declarado con ``attempts`` (el contador de B2-12), nunca
perdiendo el resto del lote. El mensaje NO revive: ``processed_at`` ya esta
puesto y reprocesarlo duplicaria la notificacion in-app.

F2-03 (2026-09-24): cada mail es su propia fila ``email.send``. Lo que el
presupuesto no alcanza ya no se declara perdido: queda pendiente para el tick
siguiente. Un envio que falla se declara en SU fila de mail.
"""

from __future__ import annotations

import smtplib
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import modules.payments.jobs as jobs
from sqlalchemy import select

from modules.payments.model import OutboxMessage
from tests.integration.test_recordatorios_sesion_smtp import _SmtpFalso


def _mensajes(cantidad: int) -> list[OutboxMessage]:
    """Eventos que producen un mail al cliente sin depender de la base."""
    return [
        OutboxMessage(
            store_id="tienda-aud2-b4-02",
            event_type="appointment.cancelled_by_block",
            payload={
                "public_id": f"turno-{indice}",
                "client_email": f"cliente-{indice}@example.com",
                "client_name": f"Cliente {indice}",
                "service": "Consulta",
            },
        )
        for indice in range(cantidad)
    ]


async def _mails(session: AsyncSession) -> dict[str, OutboxMessage]:
    """Filas ``email.send`` por destinatario, releidas de la base."""
    filas = (
        (
            await session.execute(
                select(OutboxMessage)
                .where(OutboxMessage.event_type == jobs.EVENT_EMAIL_SEND)
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    return {destino_del_mail(fila): fila for fila in filas}


def destino_del_mail(fila: OutboxMessage) -> str:
    """Destinatario guardado en una fila ``email.send``."""
    argumentos = fila.payload.get("args")
    assert isinstance(argumentos, dict), fila.payload
    return str(argumentos.get("email"))


class _RelojFalso:
    """Reloj monotonico manual: cada envio "tarda" lo que se le indique."""

    def __init__(self) -> None:
        self.ahora = 1000.0

    def monotonic(self) -> float:
        return self.ahora


@pytest.mark.asyncio
async def test_el_lote_manda_todos_los_mails_con_una_sola_conexion(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    commits = {"n": 0}
    commit_real = AsyncSession.commit

    # A nivel de clase: desde el v-diff de AUD2-B4-02 el lote commitea con
    # ``AsyncSession.commit(db)`` (no con el metodo de la instancia), asi que
    # un espia sobre ``test_session.commit`` no lo veria.
    async def contar_commit(self: AsyncSession) -> None:
        commits["n"] += 1
        await commit_real(self)

    class _SmtpEspia(_SmtpFalso):
        commits_al_conectar: list[int] = []

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            _SmtpEspia.commits_al_conectar.append(commits["n"])

    _SmtpEspia.commits_al_conectar = []
    _SmtpFalso.reset()
    monkeypatch.setattr(smtplib, "SMTP", _SmtpEspia)

    for mensaje in _mensajes(5):
        test_session.add(mensaje)
    await test_session.commit()
    monkeypatch.setattr(AsyncSession, "commit", contar_commit)

    resultado = await jobs.process_outbox_batch(test_session)

    assert resultado["processed"] == 5
    assert len(_SmtpFalso.enviados) == 5
    assert _SmtpFalso.conexiones == 1, "una conexion por lote, no una por mail"
    assert _SmtpFalso.logins == 1
    assert _SmtpFalso.quits == 1, "la sesion se cierra al terminar el lote"
    # Guarda viva (regla 5 / "ningun consumidor del outbox manda mail dentro de
    # su transaccion"): el SMTP se toca recien despues del commit del lote (1)
    # y del commit del reclamo de su primer mail (2, F2-03).
    assert _SmtpEspia.commits_al_conectar == [2]


@pytest.mark.asyncio
async def test_un_lote_sin_mails_no_abre_conexion(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El QUIT no puede correr con el FOR UPDATE del lote sin commitear."""
    _SmtpFalso.reset()
    monkeypatch.setattr(smtplib, "SMTP", _SmtpFalso)

    resultado = await jobs.process_outbox_batch(test_session)

    assert resultado["inspected"] == 0
    assert (_SmtpFalso.conexiones, _SmtpFalso.quits) == (0, 0)


@pytest.mark.asyncio
async def test_el_presupuesto_corta_el_despacho_y_difiere_el_resto(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    reloj = _RelojFalso()
    monkeypatch.setattr(jobs, "time", SimpleNamespace(monotonic=reloj.monotonic))
    tardanza = jobs.OUTBOX_EMAIL_BUDGET_SECONDS * 0.6
    enviados: list[str] = []

    async def envio_lento(
        *, email: str | None, details: dict[str, Any], smtp: Any = None
    ) -> dict[str, str]:
        reloj.ahora += tardanza
        enviados.append(str(email))
        return {"status": "sent", "to": str(email)}

    monkeypatch.setattr(jobs, "send_cancellation_email", envio_lento)
    mensajes = _mensajes(4)
    for mensaje in mensajes:
        test_session.add(mensaje)
    await test_session.commit()

    resultado = await jobs.process_outbox_batch(test_session)

    # 0 s y 0.6 del presupuesto entran; al tercero (1.2) ya vencio.
    assert resultado["processed"] == 4
    assert len(enviados) == 2
    for mensaje in mensajes:
        await test_session.refresh(mensaje)
        assert mensaje.attempts == 0
        assert mensaje.error is None
        assert mensaje.processed_at is not None, (
            "no revive: reprocesarlo duplicaria la notificacion in-app"
        )
    # F2-03: los que no entraron no se pierden; esperan sin intento contado.
    pendientes = [
        m for m in (await _mails(test_session)).values() if m.processed_at is None
    ]
    assert len(pendientes) == 2
    assert all(m.attempts == 0 and m.error is None for m in pendientes)

    # El tick siguiente los manda, sin repetir los ya enviados.
    await jobs.process_outbox_batch(test_session)
    assert sorted(enviados) == [f"cliente-{i}@example.com" for i in range(4)]
    assert all(
        m.processed_at is not None for m in (await _mails(test_session)).values()
    )


@pytest.mark.asyncio
async def test_un_mail_que_falla_no_se_lleva_el_resto_del_lote(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    enviados: list[str] = []

    async def envio(
        *, email: str | None, details: dict[str, Any], smtp: Any = None
    ) -> dict[str, str]:
        if email == "cliente-1@example.com":
            raise ConnectionRefusedError("smtp caido")
        enviados.append(str(email))
        return {"status": "sent", "to": str(email)}

    monkeypatch.setattr(jobs, "send_cancellation_email", envio)
    mensajes = _mensajes(3)
    for mensaje in mensajes:
        test_session.add(mensaje)
    await test_session.commit()

    resultado = await jobs.process_outbox_batch(test_session)

    assert resultado["processed"] == 3
    assert sorted(enviados) == ["cliente-0@example.com", "cliente-2@example.com"]
    # El fallo queda en la fila del mail (F2-03), procesada: no se reintenta.
    mails = await _mails(test_session)
    assert mails["cliente-1@example.com"].attempts == 1
    assert mails["cliente-1@example.com"].error == "ConnectionRefusedError"
    assert mails["cliente-1@example.com"].processed_at is not None
    for indice in (0, 2):
        assert mails[f"cliente-{indice}@example.com"].attempts == 0
    for mensaje in mensajes:
        await test_session.refresh(mensaje)
        assert mensaje.attempts == 0


@pytest.mark.asyncio
async def test_un_smtp_que_devuelve_false_tambien_queda_declarado(
    test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``send_*_email`` no propaga: devuelve ``{"status": "failed"}``."""
    monkeypatch.setattr(smtplib, "SMTP", _SmtpFalso)
    _SmtpFalso.reset(caer_en_intento={0})
    [mensaje] = _mensajes(1)
    test_session.add(mensaje)
    await test_session.commit()

    await jobs.process_outbox_batch(test_session)

    fila = (await _mails(test_session))["cliente-0@example.com"]
    assert fila.attempts == 1
    assert fila.error == "smtp"
