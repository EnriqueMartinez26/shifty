"""Los mails del panel salen despues del commit, sin transaccion y con el cache ya invalidado.

2026-09-24, F1-05 (R8-05): en ``AppointmentService.book`` el mail iba ANTES
de ``invalidate_availability``: con un SMTP lento (10 s por operacion) la
disponibilidad publica seguia mostrando libre un horario ya tomado todo ese
rato. Y ``confirm``, ``complete`` y ``reschedule`` releian la tienda DESPUES
del commit, asi que el SMTP corria con una transaccion recien abierta
(``idle in transaction`` en Postgres, con el pool de 15).

Ahora: lo que el mail necesita se lee antes del commit; commit plano,
invalidacion, mail y recien despues se reaplica el contexto. En SQLite se
observa el orden con eventos del engine; el estado de la conexion en
Postgres lo fija ``tests/postgres/test_pg_sin_idle_en_transaccion.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine

import modules.appointments.service as appointments_service
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)
from tests.integration.test_lotes_sin_transaccion_abierta import (
    _dejar_de_escuchar,
    _escuchar,
)


def _registrar_mails_e_invalidaciones(
    monkeypatch: pytest.MonkeyPatch, linea: list[str]
) -> None:
    async def mail(*args: Any, **kwargs: Any) -> bool:
        linea.append("mail")
        return True

    for nombre in ("send_confirmation_email", "send_rebook_email", "send_reschedule_email"):
        monkeypatch.setattr(appointments_service, nombre, mail)

    invalidar_original = appointments_service.invalidate_availability

    async def invalidar(*args: Any, **kwargs: Any) -> None:
        linea.append("invalidar")
        await invalidar_original(*args, **kwargs)

    monkeypatch.setattr(appointments_service, "invalidate_availability", invalidar)


def _tramo_del_mail(linea: list[str]) -> list[str]:
    """Lo que paso entre el ultimo commit anterior al mail y el mail."""
    assert linea.count("mail") == 1, linea
    mail = linea.index("mail")
    commits = [i for i, e in enumerate(linea[:mail]) if e == "commit"]
    assert commits, f"el mail salio sin commit previo: {linea}"
    return linea[commits[-1] + 1 : mail]


async def _pedir(
    engine: AsyncEngine, linea: list[str], pedido: Any
) -> Any:
    linea.clear()
    sql, commit = _escuchar(engine, linea)
    try:
        return await pedido()
    finally:
        _dejar_de_escuchar(engine, sql, commit)


async def _agenda(client: AsyncClient, slug: str) -> tuple[str, str, str, datetime]:
    _store, token = await register_and_login(client, slug=slug, email=f"{slug}@t.com")
    servicio = await create_service(client, token)
    staff = await create_staff(client, token, servicio, email=f"pro-{slug}@t.com")
    dia = datetime.now(timezone.utc) + timedelta(days=6)
    await add_staff_schedule(client, token, staff, target_date=dia)
    return token, servicio, staff, dia


@pytest.mark.asyncio
async def test_reservar_desde_el_panel_invalida_antes_del_mail_y_sin_sql_en_el_medio(
    client: AsyncClient, test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    linea: list[str] = []
    _registrar_mails_e_invalidaciones(monkeypatch, linea)
    token, servicio, staff, dia = await _agenda(client, "f105-book")

    async def reservar() -> Any:
        return await client.post(
            "/appointments/",
            headers=auth_headers(token),
            json={
                "service_id": servicio,
                "staff_id": staff,
                "starts_at": dia.replace(hour=10, minute=0, second=0, microsecond=0).isoformat(),
                "idempotency_key": "f105-book-turno",
            },
        )

    res = await _pedir(test_engine, linea, reservar)

    assert res.status_code == 201, res.text
    assert _tramo_del_mail(linea) == ["invalidar"], linea


@pytest.mark.asyncio
async def test_confirmar_completar_y_reprogramar_mandan_el_mail_sin_sql_despues_del_commit(
    client: AsyncClient, test_engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    linea: list[str] = []
    _registrar_mails_e_invalidaciones(monkeypatch, linea)
    token, servicio, staff, dia = await _agenda(client, "f105-estados")
    turnos = []
    for hora in (10, 11):
        res = await client.post(
            "/appointments/",
            headers=auth_headers(token),
            json={
                "service_id": servicio,
                "staff_id": staff,
                "starts_at": dia.replace(hour=hora, minute=0, second=0, microsecond=0).isoformat(),
                "idempotency_key": f"f105-estados-{hora}",
            },
        )
        assert res.status_code == 201, res.text
        turnos.append(res.json()["public_id"])
    headers = auth_headers(token)

    async def confirmar() -> Any:
        return await client.patch(f"/appointments/{turnos[0]}/confirm", headers=headers)

    res = await _pedir(test_engine, linea, confirmar)
    assert res.status_code == 200, res.text
    assert _tramo_del_mail(linea) == [], f"confirmar: {linea}"

    async def completar() -> Any:
        return await client.patch(f"/appointments/{turnos[0]}/complete", headers=headers)

    res = await _pedir(test_engine, linea, completar)
    assert res.status_code == 200, res.text
    assert _tramo_del_mail(linea) == [], f"completar: {linea}"

    async def reprogramar() -> Any:
        return await client.patch(
            f"/appointments/{turnos[1]}/reschedule",
            headers=headers,
            json={
                "new_starts_at": dia.replace(hour=12, minute=0, second=0, microsecond=0).isoformat(),
                "idempotency_key": "f105-estados-reprog",
            },
        )

    res = await _pedir(test_engine, linea, reprogramar)
    assert res.status_code == 200, res.text
    assert _tramo_del_mail(linea) == ["invalidar"], f"reprogramar: {linea}"
