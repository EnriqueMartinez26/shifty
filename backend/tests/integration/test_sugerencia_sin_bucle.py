"""La sugerencia de horario ante un choque no consulta la base por intento.

Audit B1-15 (2026-09-18), regla 12 de CLAUDE.md. Sintoma: ``_find_suggestion``
avanzaba de a un hueco y por CADA intento hacia dos consultas (bloqueo y
choque), hasta 48 round-trips, dentro del request y con el ``FOR UPDATE`` del
profesional tomado: justo el camino que se dispara en rafaga cuando varios
clientes pelean el mismo slot.

Ahora trae turnos y bloqueos de la ventana de busqueda (6 horas) en una
consulta cada uno y recorre en memoria con el mismo criterio (buffer
incluido). La sugerencia tiene que seguir siendo reservable.
"""

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from core.utils import ensure_utc_aware
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
)


def _espiar(session: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    registro: list[str] = []
    original = session.execute

    async def execute_espiado(statement: Any, *args: Any, **kwargs: Any) -> Any:
        # Por el SQL renderizado: con joinedload + limit la consulta de choque
        # sale envuelta en una subconsulta anonima y no expone la tabla.
        sql = str(statement)
        if "FROM appointment_blocks" in sql:
            registro.append("leer_bloqueos")
        elif "FROM appointments" in sql:
            registro.append("leer_turnos")
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(session, "execute", execute_espiado)
    return registro


async def _turno(
    client: AsyncClient, token: str, service: str, staff: str, inicio: datetime, n: int
) -> Any:
    return await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": service,
            "staff_id": staff,
            "starts_at": inicio.isoformat(),
            "idempotency_key": f"sugerencia-{n:04d}",
        },
    )


@pytest.mark.asyncio
async def test_la_sugerencia_salta_turnos_y_bloqueos_sin_consultar_por_intento(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _store, token = await register_and_login(
        client, slug="sugerencia", email="sugerencia@example.com"
    )
    service = await create_service(client, token)  # 30 minutos
    staff = await create_staff(client, token, service, email="pro-sug@example.com")
    base = (datetime.now(timezone.utc) + timedelta(days=5)).replace(
        hour=13, minute=0, second=0, microsecond=0
    )

    # Agenda: turno 13:00-13:30, bloqueo 13:40-14:00, turno 14:00-14:30.
    assert (await _turno(client, token, service, staff, base, 1)).status_code == 201
    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": staff,
            "starts_at": (base + timedelta(minutes=40)).isoformat(),
            "ends_at": (base + timedelta(minutes=60)).isoformat(),
            "reason": "Pausa",
        },
    )
    assert bloqueo.status_code == 201, bloqueo.text
    segundo = await _turno(client, token, service, staff, base + timedelta(hours=1), 2)
    assert segundo.status_code == 201, segundo.text
    buffer = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"buffer_minutes": 10}
    )
    assert buffer.status_code == 200, buffer.text

    registro = _espiar(test_session, monkeypatch)
    choque = await _turno(client, token, service, staff, base, 3)

    assert choque.status_code == 409, choque.text
    # 13:30 cae en el bloqueo -> 14:00 choca con el turno (+10 de buffer)
    # -> 14:40 esta libre.
    esperado = base + timedelta(minutes=100)
    detalle = choque.json()
    sugerencia = (detalle.get("detail") or detalle)["suggestion"]
    # SQLite devuelve naive: todo lo guardado es UTC.
    assert ensure_utc_aware(datetime.fromisoformat(sugerencia)) == esperado, detalle
    # Regla 12: la validacion lee una vez cada tabla y la sugerencia otra
    # vez cada una, sin importar cuantos huecos recorra (antes 4 + 3).
    assert registro.count("leer_bloqueos") == 2, registro
    assert registro.count("leer_turnos") == 2, registro

    monkeypatch.undo()
    # La sugerencia se puede reservar tal cual (mismo criterio de buffer).
    tomada = await _turno(client, token, service, staff, esperado, 4)
    assert tomada.status_code == 201, tomada.text
