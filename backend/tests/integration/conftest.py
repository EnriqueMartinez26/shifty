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
from core.models import Base
from main import app

# Importados por su efecto: registran los modelos en Base.metadata antes de
# crear las tablas.
import modules.appointments.model  # noqa: F401
import modules.audit.model  # noqa: F401
import modules.auth.session_model  # noqa: F401
import modules.budget.model  # noqa: F401
import modules.ledger.model  # noqa: F401
import modules.notifications.model  # noqa: F401
import modules.otp.model  # noqa: F401
import modules.payments.model  # noqa: F401
import modules.promotions.model  # noqa: F401
import modules.services.model  # noqa: F401
import modules.staff.model  # noqa: F401
import modules.stores.model  # noqa: F401
import modules.users.model  # noqa: F401

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
    settings.ALLOW_PUBLIC_REGISTRATION = True

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
