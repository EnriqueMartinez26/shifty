"""PV-01 contra Postgres real: email de cliente por tienda, del personal global.

2026-09-25 (auditoria de privacidad PV-01, decision de Mateo). La base es la
garantia, no el pre-chequeo:

- ``uq_users_client_email_per_store``: UNIQUE ``(store_id, email)`` WHERE
  ``role = 'client'``.
- ``uq_users_email_non_client``: UNIQUE ``(email)`` WHERE ``role <> 'client'``.
- ``ix_users_email`` queda como indice comun (la igualdad del login bajo RLS)
  y el funcional global ``uq_users_email_lower`` ya no existe.

SQLite no prueba la carrera: N reservas publicas simultaneas en UNA tienda
con el mismo email y telefonos distintos dejan un solo cliente, el resto 409
y cero 5xx; en dos tiendas, las dos entran. Bajo RLS el pre-chequeo del alta
de personal no ve las otras tiendas: el email de otra tienda lo frena el
indice (409 neutro). El downgrade se detiene con el conteo si hay un email en
dos filas: no elige por nadie.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import ulid
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import alembic, auth_headers, register_and_login

pytestmark = pytest.mark.postgres

EMAIL = "ana@example.com"
RAFAGA = 8
REVISION = "4b6d8f0a2c13"
ANTERIOR = "a3c5e7f9b1d2"


async def _tienda(
    client: AsyncClient, sessions: async_sessionmaker[AsyncSession], slug: str
) -> tuple[str, str, str, str, datetime]:
    store, token = await register_and_login(
        client, sessions, slug=slug, email=f"{slug}@demo.com"
    )
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    # 10:00 UTC = 07:00 local, dentro de la jornada de 06 a 18 local.
    slot = dia.replace(hour=10, minute=0, second=0, microsecond=0)
    return store, token, service, staff, slot


def _reserva(
    store: str, service: str, staff: str, slot: datetime, i: int, key: str
) -> dict[str, Any]:
    return {
        "store_public_id": store,
        "service_id": service,
        "staff_id": staff,
        "starts_at": (slot + timedelta(minutes=30 * i)).isoformat(),
        "client_name": f"Ana {i}",
        "client_phone": f"+54911666{i:05d}",
        "accepts_terms": True,
        "client_email": EMAIL,
        "idempotency_key": key,
    }


async def _filas(owner_engine: AsyncEngine, email: str) -> list[tuple[str, str]]:
    async with owner_engine.connect() as conn:
        return [
            (str(r[0]), str(r[1]))
            for r in (
                await conn.execute(
                    text("select store_id, role from users where email = :e"),
                    {"e": email},
                )
            ).all()
        ]


async def _insertar(
    owner_engine: AsyncEngine, *, store_id: str, email: str, role: str
) -> None:
    async with owner_engine.begin() as conn:
        await conn.execute(
            text(
                "insert into users (id, email, hashed_password, role, store_id, "
                "is_global_admin, is_active, created_at, updated_at) values "
                "(:id, :email, 'x', :role, :store_id, false, true, now(), now())"
            ),
            {
                "id": str(ulid.ULID()),
                "email": email,
                "role": role,
                "store_id": store_id,
            },
        )


@pytest.mark.asyncio
async def test_los_indices_de_email_quedan_partidos_por_rol(
    owner_engine: AsyncEngine,
) -> None:
    async with owner_engine.connect() as conn:
        indices = {
            str(r[0]): str(r[1])
            for r in (
                await conn.execute(
                    text(
                        "select indexname, indexdef from pg_indexes "
                        "where tablename = 'users'"
                    )
                )
            ).all()
        }
    assert "uq_users_email_lower" not in indices
    assert "UNIQUE" not in indices["ix_users_email"]
    cliente = indices["uq_users_client_email_per_store"]
    assert "UNIQUE" in cliente and "(store_id, email)" in cliente
    assert "'client'" in cliente and "=" in cliente.split("WHERE", 1)[1]
    personal = indices["uq_users_email_non_client"]
    assert "UNIQUE" in personal and "(email)" in personal
    assert "<>" in personal.split("WHERE", 1)[1]


@pytest.mark.asyncio
async def test_la_base_parte_la_unicidad_del_email_por_rol(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    alfa, *_ = await _tienda(client, app_sessions, "pv01-base-alfa")
    beta, *_ = await _tienda(client, app_sessions, "pv01-base-beta")

    # El mismo email: cliente en alfa, cliente en beta y profesional en beta.
    await _insertar(owner_engine, store_id=alfa, email=EMAIL, role="client")
    await _insertar(owner_engine, store_id=beta, email=EMAIL, role="client")
    await _insertar(owner_engine, store_id=beta, email=EMAIL, role="staff")

    with pytest.raises(IntegrityError, match="uq_users_client_email_per_store"):
        await _insertar(owner_engine, store_id=alfa, email=EMAIL, role="client")
    with pytest.raises(IntegrityError, match="uq_users_email_non_client"):
        await _insertar(owner_engine, store_id=alfa, email=EMAIL, role="admin")
    assert len(await _filas(owner_engine, EMAIL)) == 3


@pytest.mark.asyncio
async def test_rafaga_publica_con_el_mismo_email_en_una_tienda_deja_un_cliente(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    store, _token, service, staff, slot = await _tienda(
        client, app_sessions, "pv01-rafaga"
    )
    respuestas = await asyncio.gather(
        *(
            client.post(
                "/public/appointments",
                json=_reserva(store, service, staff, slot, i, f"pv01-rafaga-{i}"),
            )
            for i in range(RAFAGA)
        )
    )
    codigos = sorted(r.status_code for r in respuestas)

    assert all(c < 500 for c in codigos), codigos
    assert codigos.count(201) == 1, codigos
    assert codigos.count(409) == RAFAGA - 1, codigos
    for r in respuestas:
        if r.status_code == 409:
            assert r.json()["error_code"] in {"RESOURCE_CONFLICT", "CONFLICT"}, r.text
            assert EMAIL not in r.text
    assert await _filas(owner_engine, EMAIL) == [(store, "client")]


@pytest.mark.asyncio
async def test_el_mismo_email_en_dos_tiendas_a_la_vez_entra_en_las_dos(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    alfa = await _tienda(client, app_sessions, "pv01-dos-alfa")
    beta = await _tienda(client, app_sessions, "pv01-dos-beta")
    respuestas = await asyncio.gather(
        *(
            client.post(
                "/public/appointments",
                json=_reserva(t[0], t[2], t[3], t[4], 0, f"pv01-dos-{n}"),
            )
            for n, t in enumerate((alfa, beta))
        )
    )
    assert [r.status_code for r in respuestas] == [201, 201], [
        r.text for r in respuestas
    ]
    assert sorted(await _filas(owner_engine, EMAIL)) == sorted(
        [(alfa[0], "client"), (beta[0], "client")]
    )


@pytest.mark.asyncio
async def test_el_email_de_un_profesional_de_otra_tienda_es_409_neutro(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    await _tienda(client, app_sessions, "pv01-pro-alfa")
    _beta, token, service, _staff, _slot = await _tienda(
        client, app_sessions, "pv01-pro-beta"
    )
    # Bajo RLS el pre-chequeo de beta no ve a alfa: frena el indice parcial.
    res = await client.post(
        "/staff/",
        headers=auth_headers(token),
        json={
            "display_name": "Dup",
            "first_name": "Dup",
            "last_name": "Licado",
            "email": "pro-pv01-pro-alfa@demo.com",
            "service_ids": [service],
        },
    )
    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "RESOURCE_CONFLICT"
    assert "pv01-pro-alfa" not in res.text
    assert len(await _filas(owner_engine, "pro-pv01-pro-alfa@demo.com")) == 1


@pytest.mark.asyncio
async def test_el_login_no_ve_al_cliente_con_el_email_del_dueno(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    await _tienda(client, app_sessions, "pv01-login-alfa")
    beta = await _tienda(client, app_sessions, "pv01-login-beta")
    cuerpo = _reserva(beta[0], beta[2], beta[3], beta[4], 0, "pv01-login")
    cuerpo["client_email"] = "pv01-login-alfa@demo.com"
    reserva = await client.post("/public/appointments", json=cuerpo)
    assert reserva.status_code == 201, reserva.text
    assert len(await _filas(owner_engine, "pv01-login-alfa@demo.com")) == 2

    login = await client.post(
        "/auth/login",
        json={"email": "PV01-login-alfa@demo.com", "password": "Password123!"},
    )
    assert login.status_code == 200, login.text
    olvido = await client.post(
        "/auth/forgot-password", json={"email": "pv01-login-alfa@demo.com"}
    )
    assert olvido.status_code == 200, olvido.text


@pytest.mark.asyncio
async def test_el_downgrade_se_detiene_con_el_conteo_si_un_email_esta_en_dos_tiendas(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    alfa, *_ = await _tienda(client, app_sessions, "pv01-baja-alfa")
    beta, *_ = await _tienda(client, app_sessions, "pv01-baja-beta")
    await _insertar(owner_engine, store_id=alfa, email=EMAIL, role="client")
    await _insertar(owner_engine, store_id=beta, email=EMAIL, role="client")

    try:
        abajo = alembic("downgrade", ANTERIOR)
        assert abajo.returncode != 0
        assert "1 email(s) en mas de una fila" in abajo.stderr, abajo.stderr[-2000:]
        async with owner_engine.connect() as conn:
            version = (
                await conn.execute(text("select version_num from alembic_version"))
            ).scalar_one()
        assert version == REVISION

        # Sin el duplicado el downgrade restaura la unicidad global y vuelve.
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("delete from users where email = :e and store_id = :s"),
                {"e": EMAIL, "s": beta},
            )
        abajo = alembic("downgrade", ANTERIOR)
        assert abajo.returncode == 0, abajo.stderr[-2000:]
        async with owner_engine.connect() as conn:
            indices = {
                str(r[0]): str(r[1])
                for r in (
                    await conn.execute(
                        text(
                            "select indexname, indexdef from pg_indexes "
                            "where tablename = 'users'"
                        )
                    )
                ).all()
            }
        assert "UNIQUE" in indices["ix_users_email"]
        assert "uq_users_email_lower" in indices
        assert "uq_users_client_email_per_store" not in indices
        assert "uq_users_email_non_client" not in indices
    finally:
        arriba = alembic("upgrade", "head")
        assert arriba.returncode == 0, arriba.stderr[-2000:]
