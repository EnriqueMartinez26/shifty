"""Fixtures compartidas por los tests de integracion.

Levantan una base SQLite en memoria por test y un cliente HTTP contra la app
real, con la sesion inyectada para poder inspeccionar el estado despues de cada
request.
"""

from typing import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import settings
from core.database import get_db
from core.model_registry import load_all_models
from core.models import Base
from main import app

# Base.metadata se puebla desde el registro, no desde una lista paralela
# (2026-09-17, C-13). La de aca tenia trece imports a mano, sin billing ni
# waitlist; create_all igual veia las 27 tablas porque `from main import app`
# carga todos los modelos por los routers. El defecto era la duplicacion: una
# copia del registro que nadie vigilaba y que falla el dia que un modelo no
# cuelgue de un router.
load_all_models()

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def test_engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_session(test_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    session_local = async_sessionmaker(
        bind=test_engine,
        expire_on_commit=False,
        autoflush=False,
    )
    async with session_local() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(test_session: AsyncSession) -> AsyncIterator[AsyncClient]:

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield test_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"x-raw-response": "true"},
    ) as c:
        yield c
    app.dependency_overrides.pop(get_db, None)
