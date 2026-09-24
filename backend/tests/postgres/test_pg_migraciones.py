"""La cadena de migraciones construye el esquema completo desde cero.

Es exactamente lo que hace el deploy en una base nueva. Se verifica que
queden las garantias que el resto del paquete ejercita (exclusion GiST,
triggers, RLS forzada, rol sin bypass) y que la ultima migracion sea
reversible.
"""

import os
import subprocess
import sys
import time

import psycopg2
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.postgres.conftest import (
    APP_URL,
    BACKEND_ROOT,
    OWNER_URL,
    _app_password,
    _sync_dsn,
    alembic,
)

pytestmark = pytest.mark.postgres


def _head() -> str:
    heads = alembic("heads")
    assert heads.returncode == 0, heads.stderr
    return heads.stdout.split()[0]


def _current() -> str:
    current = alembic("current")
    assert current.returncode == 0, current.stderr
    return current.stdout.split()[0]


def _merge_parents(rev: str) -> list[str]:
    """Padres de `rev` si es un mergepoint; lista vacia si no lo es."""
    show = alembic("show", rev)
    assert show.returncode == 0, show.stderr
    lines = show.stdout.splitlines()
    if "(mergepoint)" not in lines[0]:
        return []
    for line in lines:
        if line.startswith("Merges:"):
            return [r.strip() for r in line.removeprefix("Merges:").split(",")]
    raise AssertionError(f"mergepoint sin linea 'Merges:': {show.stdout}")


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
    # Un mergepoint tiene dos padres: "-1" es ambiguo (Alembic no sabe a
    # cual de los dos volver) y falla con "Ambiguous walk". Bajar a
    # cualquiera de los padres explicitos prueba lo mismo que "-1" en el
    # caso lineal: que el head no deja la base encallada sin poder volver.
    merge_parents = _merge_parents(head)
    down = alembic("downgrade", merge_parents[0] if merge_parents else "-1")
    assert down.returncode == 0, down.stderr[-2000:]
    assert _current() != head
    up = alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr[-2000:]
    assert _current() == head


# Tablas con store_id que son globales A PROPOSITO y por eso no llevan RLS.
# `audit_logs` la deja afuera la migracion c3d4e5f6a7b8, que lo dice: "es
# global por diseno y la consulta el panel de superadministracion, que necesita
# ver todas las tiendas". Agregar una tabla aca es una decision del dueno, no
# del test: si aparece una nueva, este test falla y hay que justificarla.
SIN_RLS_A_PROPOSITO = {"audit_logs"}

# Multi-tenant SIN columna store_id: la consulta por columna no las encuentra,
# pero llevan RLS igual. `stores` ES la tienda (su policy compara `id`) y
# `staff_services` cuelga de staff (su policy hace EXISTS contra staff.store_id;
# ver d5ec116d06a3). Al reemplazar los pisos globales por la verificacion por
# columna, estas dos quedaban sin cobertura (V-diff de AUD2-C-11, 2026-09-20).
RLS_OBLIGATORIA_SIN_STORE_ID = {"stores", "staff_services"}


@pytest.mark.asyncio
async def test_toda_tabla_con_store_id_tiene_rls_forzado_y_politica(
    owner_engine: AsyncEngine,
) -> None:
    """AUD2-C-11 (2026-09-19): el esquema se validaba con pisos globales.

    Sintoma: el test de esquema pedia `politicas >= 25` y `forzadas >= 20`,
    conteos sobre el total. Con 27 tablas y 23 columnas store_id habia holgura
    de sobra: una tabla multi-tenant nueva a la que se le olvidara
    ENABLE/FORCE ROW LEVEL SECURITY y su policy no bajaba ningun numero por
    debajo del piso y el job pasaba verde. CLAUDE.md: "RLS es la garantia", y
    la garantia se verificaba por conteo.
    """
    async with owner_engine.connect() as conn:
        con_store_id = {
            r[0]
            for r in (
                await conn.execute(
                    text(
                        "select table_name from information_schema.columns "
                        "where table_schema='public' and column_name='store_id'"
                    )
                )
            ).all()
        }
        estado = {
            r[0]: (r[1], r[2])
            for r in (
                await conn.execute(
                    text(
                        "select c.relname, c.relrowsecurity, c.relforcerowsecurity "
                        "from pg_class c join pg_namespace n on n.oid = c.relnamespace "
                        "where n.nspname='public' and c.relkind='r'"
                    )
                )
            ).all()
        }
        con_politica = {
            r[0]
            for r in (
                await conn.execute(
                    text(
                        "select distinct tablename from pg_policies where schemaname='public'"
                    )
                )
            ).all()
        }

    assert con_store_id, "ninguna tabla tiene store_id: la consulta no sirve"
    assert RLS_OBLIGATORIA_SIN_STORE_ID <= set(estado), (
        "la lista de tablas sin store_id nombra tablas que no existen: "
        f"{sorted(RLS_OBLIGATORIA_SIN_STORE_ID - set(estado))}"
    )
    assert not (RLS_OBLIGATORIA_SIN_STORE_ID & con_store_id), (
        "estas tablas ya tienen store_id: la consulta por columna las cubre y "
        f"sobran en la lista: {sorted(RLS_OBLIGATORIA_SIN_STORE_ID & con_store_id)}"
    )

    exigidas = (con_store_id - SIN_RLS_A_PROPOSITO) | RLS_OBLIGATORIA_SIN_STORE_ID
    faltan_rls: list[str] = []
    faltan_force: list[str] = []
    faltan_politica: list[str] = []
    for tabla in sorted(exigidas):
        habilitada, forzada = estado.get(tabla, (False, False))
        if not habilitada:
            faltan_rls.append(tabla)
        if not forzada:
            faltan_force.append(tabla)
        if tabla not in con_politica:
            faltan_politica.append(tabla)

    assert not faltan_rls, (
        f"tablas con store_id sin ENABLE ROW LEVEL SECURITY: {faltan_rls}"
    )
    assert not faltan_force, (
        "tablas con store_id sin FORCE ROW LEVEL SECURITY (el dueno de la tabla "
        f"las lee enteras): {faltan_force}"
    )
    assert not faltan_politica, (
        f"tablas con store_id sin ninguna policy: {faltan_politica}"
    )

    # La lista de excepciones no puede crecer sola ni quedar obsoleta.
    assert SIN_RLS_A_PROPOSITO <= con_store_id, (
        "la excepcion nombra tablas que ya no tienen store_id: "
        f"{sorted(SIN_RLS_A_PROPOSITO - con_store_id)}"
    )


@pytest.mark.asyncio
async def test_una_migracion_que_espera_un_lock_aborta_en_segundos(
    owner_engine: AsyncEngine,
) -> None:
    """F0-06 (plan de rendimiento): `lock_timeout` en la sesion de Alembic.

    Sintoma que previene: una migracion que espera un lock fuerte encola
    detras de ella todas las consultas de la app sobre esa tabla; el deploy
    tumbaba la API sin que la migracion hiciera nada. Aca otra sesion retiene
    ACCESS EXCLUSIVE sobre `alembic_version` (lo primero que Alembic lee) y la
    migracion tiene que abortar por lock timeout en segundos, no quedarse
    esperando. Sin el SET de env.py, el subproceso cuelga hasta el timeout.
    """
    assert OWNER_URL and APP_URL
    antes = _current()
    bloqueo = psycopg2.connect(_sync_dsn(OWNER_URL))
    try:
        with bloqueo.cursor() as cur:
            cur.execute("LOCK TABLE alembic_version IN ACCESS EXCLUSIVE MODE")
        inicio = time.monotonic()
        try:
            corrida = subprocess.run(
                [sys.executable, "-m", "alembic", "upgrade", "head"],
                cwd=BACKEND_ROOT,
                env={
                    **os.environ,
                    "MIGRATION_DATABASE_URL": OWNER_URL,
                    "DATABASE_URL": APP_URL,
                    "APP_DB_PASSWORD": _app_password(APP_URL),
                },
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except subprocess.TimeoutExpired:
            pytest.fail("la migracion espero el lock sin tope (sin lock_timeout)")
        demora = time.monotonic() - inicio
    finally:
        bloqueo.rollback()
        bloqueo.close()

    assert corrida.returncode != 0, "la migracion no debia poder tomar el lock"
    assert "lock timeout" in corrida.stderr, corrida.stderr[-2000:]
    assert demora < 30, f"la migracion tardo {demora:.1f}s en rendirse"
    assert _current() == antes
