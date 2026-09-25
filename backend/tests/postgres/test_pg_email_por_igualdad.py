"""F1-12 (plan de rendimiento, R7-01): el login busca el email por igualdad.

2026-09-24. Sintoma: el login y el olvido de clave buscaban con
``lower(users.email) = :email``. ``lower`` no es leakproof: bajo RLS Postgres
no puede usarlo como condicion de indice y recorria ``users`` ENTERA en cada
login (Seq Scan aun con ``enable_seqscan = off``), y el olvido de clave es
publico. El indice funcional ``uq_users_email_lower`` tenia ``idx_scan = 0``.

Ahora el email vive normalizado en la columna, lo sostiene
``CHECK (email = lower(email))`` (``ck_users_email_lower``) y las consultas
comparan ``users.email = :email``, que usa ``ix_users_email``.

2026-09-25 (PV-01): el login y el olvido de clave filtran ademas ``role <>
'client'`` (el email de un cliente es unico por tienda y puede repetirse). Con
el rol como literal del plan, Postgres elige el indice unico parcial
``uq_users_email_non_client``; con un plan generico (rol como parametro) no
puede probar el predicado y usa ``ix_users_email``, que sigue como indice
comun. Los dos son igualdad sobre la columna: lo que no puede volver es el
recorrido de la tabla.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.postgres.conftest import PASSWORD, alembic, seed_store_and_admin
from tests.postgres.planes import (
    condiciones_de_indice,
    plan_de,
    resumen,
    sentencias_capturadas,
)

pytestmark = pytest.mark.postgres

REVISION_DEL_CHECK = "c4e6a8b0d2f1"
INDICES_DE_EMAIL = ("ix_users_email", "uq_users_email_non_client")


def _busquedas_por_email(
    capturadas: list[tuple[str, object]],
) -> list[tuple[str, object]]:
    return [
        (sql, params)
        for sql, params in capturadas
        if "FROM users" in sql and "users.email" in sql.split("WHERE", 1)[-1]
    ]


@pytest.mark.asyncio
async def test_login_y_olvido_de_clave_usan_el_indice_de_email(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    app_engine: AsyncEngine,
) -> None:
    await seed_store_and_admin(app_sessions, slug="email-plan", email="plan@demo.com")

    with sentencias_capturadas(app_engine) as capturadas:
        login = await client.post(
            "/auth/login", json={"email": "Plan@Demo.com", "password": PASSWORD}
        )
        olvido = await client.post(
            "/auth/forgot-password", json={"email": "PLAN@demo.com"}
        )
    assert login.status_code == 200, login.text
    assert olvido.status_code == 200, olvido.text

    busquedas = _busquedas_por_email(capturadas)
    assert len(busquedas) >= 2, [sql for sql, _ in capturadas]
    for sentencia in busquedas:
        plan = await plan_de(app_engine, sentencia, global_admin=True)
        condiciones = condiciones_de_indice(plan)
        assert any(
            "email" in condiciones.get(indice, "") for indice in INDICES_DE_EMAIL
        ), f"{sentencia[0]}\n{resumen(plan)}"


@pytest.mark.asyncio
async def test_la_base_rechaza_un_email_con_mayusculas(
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    await seed_store_and_admin(app_sessions, slug="email-check", email="check@demo.com")

    async with owner_engine.connect() as conn:
        validada = (
            await conn.execute(
                text(
                    "select convalidated from pg_constraint "
                    "where conname = 'ck_users_email_lower'"
                )
            )
        ).scalar_one()
    assert validada is True

    with pytest.raises(IntegrityError, match="ck_users_email_lower"):
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("update users set email = 'Check@demo.com' where email = :e"),
                {"e": "check@demo.com"},
            )


@pytest.mark.asyncio
async def test_la_migracion_se_detiene_con_el_conteo_si_hay_mayusculas(
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
) -> None:
    """Decision 16 del plan: la migracion no normaliza por nadie."""
    await seed_store_and_admin(
        app_sessions, slug="email-guarda", email="guarda@demo.com"
    )
    padre = alembic("show", REVISION_DEL_CHECK)
    assert padre.returncode == 0, padre.stderr
    anterior = next(
        linea.split(":", 1)[1].strip()
        for linea in padre.stdout.splitlines()
        if linea.startswith("Parent:")
    )

    abajo = alembic("downgrade", anterior)
    assert abajo.returncode == 0, abajo.stderr[-2000:]
    try:
        async with owner_engine.begin() as conn:
            await conn.execute(
                text("update users set email = 'Guarda@demo.com' where email = :e"),
                {"e": "guarda@demo.com"},
            )
        arriba = alembic("upgrade", "head")
        assert arriba.returncode != 0
        assert "1 email(s) con mayusculas" in arriba.stderr, arriba.stderr[-2000:]
    finally:
        async with owner_engine.begin() as conn:
            await conn.execute(text("update users set email = lower(email)"))
        final = alembic("upgrade", "head")
        assert final.returncode == 0, final.stderr[-2000:]
