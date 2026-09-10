"""Tests contra Postgres REAL: lo que SQLite no puede probar.

La suite de integracion corre en SQLite en memoria y por eso nunca ejercita
las garantias que hacen que un turnero no reviente: la restriccion de
exclusion GiST contra dobles reservas, el trigger de transiciones de estado,
el aislamiento por Row-Level Security y la cadena de migraciones. Este
paquete las prueba contra un Postgres de verdad, replicando el despliegue:

- Las migraciones corren desde un esquema VACIO con el rol dueno
  (``TEST_POSTGRES_MIGRATION_URL``), como en produccion.
- La aplicacion conecta como ``shifty_app`` (``TEST_POSTGRES_URL``), sin
  superusuario ni BYPASSRLS, con UNA sesion por request: sin eso no hay
  concurrencia real y las pruebas de rafaga no prueban nada.

Si las variables no estan definidas, todo el paquete se salta (asi
``uv run pytest`` a secas sigue verde). CI las define en el job
``backend-postgres``. Local, con el docker-compose levantado:

    TEST_POSTGRES_MIGRATION_URL=postgresql+asyncpg://shifty_user:shifty_password@127.0.0.1:5432/shifty_test
    TEST_POSTGRES_URL=postgresql+asyncpg://shifty_app:shifty_app_password@127.0.0.1:5432/shifty_test

Los engines son de alcance de funcion a proposito: pytest-asyncio cierra el
loop por test y un pool de asyncpg atado a un loop cerrado falla en el test
siguiente (el mismo bug que tuvo el worker de Celery).
"""

from __future__ import annotations

import os
import subprocess
import sys

import ulid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from urllib.parse import urlparse

import psycopg2
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.database import (
    TenantSession,
    _apply_tenant_context,
    get_db,
    set_tenant_context,
)
from core.model_registry import load_all_models
from core.models import Base
from core.security import hash_password
from main import app
from modules.auth.service import normalize_email
from modules.stores.model import Store
from modules.users.model import User, UserRole

BACKEND_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = Path(__file__).resolve().parent
APP_URL = os.getenv("TEST_POSTGRES_URL")
OWNER_URL = os.getenv("TEST_POSTGRES_MIGRATION_URL")
HABILITADO = bool(APP_URL and OWNER_URL)
PASSWORD = "Password123!"


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if HABILITADO:
        return
    skip = pytest.mark.skip(
        reason="Postgres real no configurado (TEST_POSTGRES_URL / "
        "TEST_POSTGRES_MIGRATION_URL); ver tests/postgres/conftest.py"
    )
    for item in items:
        if Path(str(item.fspath)).is_relative_to(PACKAGE_DIR):
            item.add_marker(skip)


def _sync_dsn(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://", 1)


def _app_password(url: str) -> str:
    return urlparse(url).password or "shifty_app_password"


def alembic(*args: str) -> subprocess.CompletedProcess[str]:
    """Corre alembic como lo hace el deploy: proceso aparte, rol dueno."""
    assert OWNER_URL and APP_URL
    env = {
        **os.environ,
        "MIGRATION_DATABASE_URL": OWNER_URL,
        "DATABASE_URL": APP_URL,
        "APP_DB_PASSWORD": _app_password(APP_URL),
    }
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


@pytest.fixture(scope="session")
def esquema_migrado() -> Iterator[None]:
    """Borra el esquema y aplica TODAS las migraciones desde cero, una vez."""
    if not HABILITADO:
        yield
        return
    assert OWNER_URL
    with psycopg2.connect(_sync_dsn(OWNER_URL)) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA public CASCADE")
            cur.execute("CREATE SCHEMA public")
    up = alembic("upgrade", "head")
    assert up.returncode == 0, f"alembic upgrade head fallo:\n{up.stderr[-3000:]}"
    yield


@pytest_asyncio.fixture
async def owner_engine(esquema_migrado: None) -> AsyncIterator[AsyncEngine]:
    """Rol dueno: para preparar y observar, NO para probar RLS."""
    assert OWNER_URL
    engine = create_async_engine(OWNER_URL, pool_size=5, max_overflow=5)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def app_engine(esquema_migrado: None) -> AsyncIterator[AsyncEngine]:
    """Rol de la aplicacion (shifty_app): sin superusuario, sujeto a RLS."""
    assert APP_URL
    engine = create_async_engine(APP_URL, pool_size=10, max_overflow=30)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(autouse=True)
async def _tablas_limpias(owner_engine: AsyncEngine) -> None:
    """Cada test arranca con las tablas vacias (el esquema se conserva)."""
    load_all_models()
    tablas = ", ".join(sorted(t.name for t in Base.metadata.sorted_tables))
    async with owner_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {tablas} RESTART IDENTITY CASCADE"))


@pytest.fixture
def app_sessions(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # class_=TenantSession es lo que reaplica el contexto RLS despues de cada
    # commit/rollback; sin eso el refresh posterior a un INSERT abre una
    # transaccion sin store_id y RLS le esconde su propia fila.
    return async_sessionmaker(
        class_=TenantSession,
        bind=app_engine,
        expire_on_commit=False,
        autoflush=False,
    )


@pytest_asyncio.fixture
async def client(
    app_sessions: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncClient]:
    """Cliente HTTP contra la app con UNA sesion por request (concurrencia real)."""

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with app_sessions() as session:
            await _apply_tenant_context(session)
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"x-raw-response": "true"},
    ) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)


async def seed_store_and_admin(
    sessions: async_sessionmaker[AsyncSession],
    *,
    slug: str,
    email: str,
    password: str = PASSWORD,
) -> str:
    """Tienda + admin escritos con el rol de la app bajo contexto de superadmin.

    Es el mismo camino que usa el alta desde el panel de superadmin: RLS
    esta forzada, asi que sin contexto global el INSERT seria rechazado.
    """
    async with sessions() as session:
        set_tenant_context(None, True)
        try:
            await _apply_tenant_context(session)
            # id y public_id son columnas independientes con default propio.
            # Se fuerzan iguales para que el store_public_id externo coincida
            # con el store_id que guardan las filas (y que usa RLS).
            store_id = str(ulid.ULID())
            store = Store(
                id=store_id,
                public_id=store_id,
                name=f"Tienda {slug}",
                slug=slug,
                theme_config={"business_type": "general"},
            )
            session.add(store)
            await session.flush()
            admin = User(
                email=normalize_email(email),
                hashed_password=hash_password(password),
                first_name="Admin",
                last_name="Demo",
                full_name="Admin Demo",
                role=UserRole.ADMIN,
                store_id=store.id,
            )
            session.add(admin)
            await session.flush()
            store_public_id = str(store.public_id)
            await session.commit()
            return store_public_id
        finally:
            set_tenant_context(None, False)


async def register_and_login(
    client: AsyncClient,
    sessions: async_sessionmaker[AsyncSession],
    *,
    slug: str,
    email: str,
) -> tuple[str, str]:
    store_public_id = await seed_store_and_admin(sessions, slug=slug, email=email)
    login = await client.post(
        "/auth/login", json={"email": email, "password": PASSWORD}
    )
    assert login.status_code == 200, login.text
    return store_public_id, str(login.json()["access_token"])


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
