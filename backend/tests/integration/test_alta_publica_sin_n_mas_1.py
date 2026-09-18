"""El alta publica con "cualquier profesional" no consulta por candidato.

Audit B1-13 (2026-09-18), regla 12 de CLAUDE.md. Sintoma: ``create_appointment``
recorria los candidatos y por CADA uno leia horarios, tomaba ``FOR UPDATE``
sobre su fila, leia bloqueos y leia choques: hasta 4*N consultas secuenciales
y un lock acumulado por cada profesional descartado (todos retenidos hasta el
commit), de modo que dos reservas del mismo servicio se serializaban aunque
fueran a profesionales distintos.

Ahora horarios, bloqueos y choques de TODOS los candidatos se leen en lote
con ``in_()``, se elige en memoria y recien se lockea el elegido. La guarda de
la regla 4 se conserva: bajo el lock se RELEEN bloqueo y choque del elegido
(la lectura en lote solo descarta), porque si no vuelve el "verificar y luego
actuar". SQLite no tiene locks de fila: aca se verifica el orden y la
cantidad de sentencias; la rafaga real esta en
tests/postgres/test_pg_reserva_concurrente.py.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from modules.staff.model import StaffBlock
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    register_and_login,
)


def _espiar(
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    antes_del_lock: Any = None,
) -> list[str]:
    """Registra en orden locks de staff y lecturas de horarios/bloqueos/turnos.

    ``antes_del_lock`` (opcional) corre justo antes del primer ``FOR UPDATE``
    sobre staff: simula otra transaccion que commitea entre la lectura en
    lote y el lock.
    """
    registro: list[str] = []
    original = session.execute

    async def execute_espiado(statement: Any, *args: Any, **kwargs: Any) -> Any:
        obtener_froms = getattr(statement, "get_final_froms", None)
        tablas = (
            {getattr(f, "name", None) for f in obtener_froms()}
            if obtener_froms
            else set()
        )
        if (
            "staff" in tablas
            and getattr(statement, "_for_update_arg", None) is not None
        ):
            if antes_del_lock is not None and "lock_staff" not in registro:
                await antes_del_lock()
            registro.append("lock_staff")
        elif "schedules" in tablas:
            registro.append("leer_horarios")
        elif "appointment_blocks" in tablas:
            registro.append("leer_bloqueos")
        elif "appointments" in tablas:
            registro.append("leer_turnos")
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(session, "execute", execute_espiado)
    return registro


async def _profesional(
    client: AsyncClient, token: str, service: str, nombre: str, slug: str
) -> str:
    res = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={
            "display_name": nombre,
            "first_name": nombre,
            "last_name": "Pro",
            "email": f"{nombre.lower()}-{slug}@example.com",
            "service_ids": [service],
        },
    )
    assert res.status_code == 201, res.text
    return cast(str, res.json()["public_id"])


def _reserva(
    store: str, service: str, slot: datetime, *, staff: str | None, i: int
) -> dict[str, object]:
    return {
        "store_public_id": store,
        "service_id": service,
        "staff_id": staff,
        "starts_at": slot.isoformat(),
        "client_name": f"Cliente {i}",
        "client_phone": f"+54911555{i:05d}",
        "idempotency_key": f"alta-lote-{i:04d}",
    }


async def _tienda_con_cuatro_candidatos(
    client: AsyncClient, slug: str
) -> tuple[str, str, str, dict[str, str], datetime]:
    store, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    service = await create_service(client, token)
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    slot = dia.replace(hour=13, minute=0, second=0, microsecond=0)  # 10:00 local
    # El desempate es por display_name: Ana, Beto, Caro, Dani.
    pros = {
        nombre: await _profesional(client, token, service, nombre, slug)
        for nombre in ("Ana", "Beto", "Caro", "Dani")
    }
    for nombre in ("Beto", "Caro", "Dani"):  # Ana no atiende ese dia
        await add_staff_schedule(client, token, pros[nombre], target_date=dia)
    return store, token, service, pros, slot


@pytest.mark.asyncio
async def test_cualquier_profesional_lee_en_lote_y_lockea_solo_al_elegido(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, token, service, pros, slot = await _tienda_con_cuatro_candidatos(
        client, "alta-lote"
    )
    bloqueo = await client.post(
        "/appointment-blocks/",
        headers=auth_headers(token),
        json={
            "staff_id": pros["Beto"],
            "starts_at": slot.isoformat(),
            "ends_at": (slot + timedelta(hours=1)).isoformat(),
            "reason": "Beto bloqueado",
        },
    )
    assert bloqueo.status_code == 201, bloqueo.text
    ocupado = await client.post(
        "/public/appointments",
        json=_reserva(store, service, slot, staff=pros["Caro"], i=1),
    )
    assert ocupado.status_code == 201, ocupado.text

    registro = _espiar(test_session, monkeypatch)
    res = await client.post(
        "/public/appointments", json=_reserva(store, service, slot, staff=None, i=2)
    )

    assert res.status_code == 201, res.text
    assert res.json()["staff_id"] == pros["Dani"], "cambio el criterio de desempate"
    # Regla 12: una lectura de horarios para los cuatro candidatos, no una
    # por candidato; y un solo lock (antes: uno por cada descartado tambien).
    assert registro.count("leer_horarios") == 1, registro
    assert registro.count("lock_staff") == 1, registro
    # Regla 4: bajo el lock del elegido se releen bloqueo y choque.
    despues_del_lock = registro[registro.index("lock_staff") + 1 :]
    assert "leer_bloqueos" in despues_del_lock, registro
    assert "leer_turnos" in despues_del_lock, registro


@pytest.mark.asyncio
async def test_la_relectura_bajo_lock_descarta_al_elegido_si_cambio_en_el_medio(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Guarda de la regla 4: la lectura en lote no decide sola.

    Entre la lectura en lote (Beto libre) y el lock, otra transaccion bloquea
    a Beto. La relectura bajo lock lo tiene que ver y pasar al siguiente
    candidato; si el alta confiara en la lectura previa, el turno quedaria
    dentro del bloqueo.
    """
    store, _token, service, pros, slot = await _tienda_con_cuatro_candidatos(
        client, "alta-relectura"
    )
    store_id = store  # el seed de tests fuerza public_id == id

    async def bloquear_a_beto_en_el_medio() -> None:
        test_session.add(
            StaffBlock(
                staff_id=pros["Beto"],
                store_id=store_id,
                start_time=slot,
                end_time=slot + timedelta(hours=1),
                reason="Carrera",
                is_active=True,
            )
        )
        await test_session.flush()

    registro = _espiar(test_session, monkeypatch, bloquear_a_beto_en_el_medio)
    res = await client.post(
        "/public/appointments", json=_reserva(store, service, slot, staff=None, i=3)
    )

    assert res.status_code == 201, res.text
    assert res.json()["staff_id"] == pros["Caro"], registro
    assert registro.count("lock_staff") == 2, registro
