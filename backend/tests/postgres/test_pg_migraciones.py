"""La cadena de migraciones construye el esquema completo desde cero.

Es exactamente lo que hace el deploy en una base nueva. Se verifica que
queden las garantias que el resto del paquete ejercita (exclusion GiST,
triggers, RLS forzada, rol sin bypass) y que la ultima migracion sea
reversible.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.postgres.conftest import alembic

pytestmark = pytest.mark.postgres


def _head() -> str:
    heads = alembic("heads")
    assert heads.returncode == 0, heads.stderr
    return heads.stdout.split()[0]


def _current() -> str:
    current = alembic("current")
    assert current.returncode == 0, current.stderr
    return current.stdout.split()[0]


@pytest.mark.asyncio
async def test_el_esquema_queda_completo_y_en_head(owner_engine: AsyncEngine) -> None:
    assert _current() == _head()

    async with owner_engine.connect() as conn:
        tablas = {
            r[0]
            for r in (
                await conn.execute(
                    text(
                        "select table_name from information_schema.tables "
                        "where table_schema='public' and table_name <> 'alembic_version'"
                    )
                )
            ).all()
        }
        politicas = (
            await conn.execute(text("select count(*) from pg_policies"))
        ).scalar_one()
        forzadas = (
            await conn.execute(
                text(
                    "select count(*) from pg_class c join pg_namespace n on n.oid=c.relnamespace "
                    "where n.nspname='public' and c.relkind='r' and c.relforcerowsecurity"
                )
            )
        ).scalar_one()
        constraints = {
            r[0]
            for r in (
                await conn.execute(
                    text("select conname from pg_constraint where conname like 'ex_%'")
                )
            ).all()
        }
        triggers = {
            r[0]
            for r in (
                await conn.execute(
                    text("select tgname from pg_trigger where not tgisinternal")
                )
            ).all()
        }
        rol = (
            await conn.execute(
                text(
                    "select rolsuper, rolbypassrls, rolconfig from pg_roles "
                    "where rolname='shifty_app'"
                )
            )
        ).one()

    criticas = {
        "appointments",
        "stores",
        "users",
        "payments",
        "auth_sessions",
        "webhook_inbox",
        "outbox_messages",
        "customer_ledger",
    }
    assert criticas <= tablas, sorted(criticas - tablas)
    assert len(tablas) >= 25, sorted(tablas)
    assert politicas >= 25, politicas
    assert forzadas >= 20, forzadas
    assert "ex_appointments_no_active_overlap" in constraints
    assert {
        "trg_appointment_transition_guard",
        "trg_appointment_ends_at_sync",
    } <= triggers
    assert rol.rolsuper is False and rol.rolbypassrls is False
    assert rol.rolconfig and any(
        item.startswith("statement_timeout=") for item in rol.rolconfig
    ), rol.rolconfig


@pytest.mark.asyncio
async def test_la_ultima_migracion_es_reversible(owner_engine: AsyncEngine) -> None:
    head = _head()
    down = alembic("downgrade", "-1")
    assert down.returncode == 0, down.stderr[-2000:]
    assert _current() != head
    up = alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr[-2000:]
    assert _current() == head
