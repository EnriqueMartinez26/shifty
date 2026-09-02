import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from typing import AsyncIterator

from core.config import settings
from core.database import get_db
from core.models import Base
from main import app
from core.security import hash_password_reset_token

# Import all modules so Base.metadata knows about all tables for SQLite test database
import modules.stores.model
import modules.users.model
import modules.services.model
import modules.staff.model
import modules.appointments.model
import modules.budget.model
import modules.audit.model

from modules.users.model import User

# Configuración de base de datos de test en memoria
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
    SessionLocal = async_sessionmaker(
        bind=test_engine, expire_on_commit=False, autoflush=False
    )
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(test_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    """
    Crea el cliente HTTP con override de la dependencia de base de datos.
    """

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


@pytest.mark.asyncio
async def test_cross_tenant_isolation(client: AsyncClient) -> None:
    # 1. Registrar Tienda A
    res_a = await client.post(
        "/auth/register",
        json={
            "store_name": "Tienda A",
            "store_slug": "tienda-a",
            "admin_email": "admin@a.com",
            "admin_password": "Password123!",
            "admin_first_name": "Admin",
            "admin_last_name": "A",
        },
    )
    assert res_a.status_code == 201

    # 2. Registrar Tienda B
    res_b = await client.post(
        "/auth/register",
        json={
            "store_name": "Tienda B",
            "store_slug": "tienda-b",
            "admin_email": "admin@b.com",
            "admin_password": "Password123!",
            "admin_first_name": "Admin",
            "admin_last_name": "B",
        },
    )
    assert res_b.status_code == 201

    # 3. Login en Tienda A
    login_a = await client.post(
        "/auth/login", json={"email": "admin@a.com", "password": "Password123!"}
    )
    token_a = login_a.json()["access_token"]

    # 4. Login en Tienda B
    login_b = await client.post(
        "/auth/login", json={"email": "admin@b.com", "password": "Password123!"}
    )
    _token_b = login_b.json()["access_token"]

    # 5. Validar aislamiento (Prueba de Fuego)
    # Pedimos '/me' con Token A -> Debe devolver store_id de A
    me_a = await client.get("/me", headers={"Authorization": f"Bearer {token_a}"})
    data_a = me_a.json()
    assert data_a["email"] == "admin@a.com"


@pytest.mark.asyncio
async def test_password_reset_flow(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_token = "test-reset-token-1234567890"

    # Evitamos dependencia SMTP en tests y fijamos token determinístico.
    monkeypatch.setattr(
        "modules.auth.service.generate_password_reset_token", lambda: reset_token
    )
    monkeypatch.setattr(
        "modules.auth.router.send_password_reset_email", lambda *_args, **_kwargs: None
    )

    register_response = await client.post(
        "/auth/register",
        json={
            "store_name": "Tienda Reset",
            "store_slug": "tienda-reset",
            "admin_email": "reset@demo.com",
            "admin_password": "Password123!",
            "admin_first_name": "Admin",
            "admin_last_name": "Reset",
        },
    )
    assert register_response.status_code == 201

    forgot_response = await client.post(
        "/auth/forgot-password", json={"email": "reset@demo.com"}
    )
    assert forgot_response.status_code == 200
    assert forgot_response.json()["message"] == (
        "Si el email existe, recibiras un enlace para restablecer la contraseña."
    )

    # Verifica que el token se haya persistido hasheado.
    result = await test_session.execute(
        select(User).where(User.email == "reset@demo.com")
    )
    user = result.scalar_one()
    assert user.password_reset_token_hash == hash_password_reset_token(reset_token)
    assert user.password_reset_expires_at is not None

    reset_response = await client.post(
        "/auth/reset-password",
        json={"token": reset_token, "new_password": "nuevaPassword123"},
    )
    assert reset_response.status_code == 200

    login_old = await client.post(
        "/auth/login", json={"email": "reset@demo.com", "password": "Password123!"}
    )
    assert login_old.status_code == 401

    login_new = await client.post(
        "/auth/login", json={"email": "reset@demo.com", "password": "nuevaPassword123"}
    )
    assert login_new.status_code == 200


@pytest.mark.asyncio
async def test_login_normalizes_email_whitespace_and_case(
    client: AsyncClient,
) -> None:
    register_response = await client.post(
        "/auth/register",
        json={
            "store_name": "Tienda Normalize",
            "store_slug": "tienda-normalize",
            "admin_email": "normalize@demo.com",
            "admin_password": "Password123!",
            "admin_first_name": "Admin",
            "admin_last_name": "Normalize",
        },
    )
    assert register_response.status_code == 201

    login_response = await client.post(
        "/auth/login",
        json={"email": "  NORMALIZE@DEMO.COM  ", "password": "Password123!"},
    )
    assert login_response.status_code == 200


@pytest.mark.asyncio
async def test_reset_password_with_invalid_token_fails(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/reset-password",
        json={"token": "invalid-token-1234567890", "new_password": "cambioSeguro123"},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_users_crud_flow_for_admin(client: AsyncClient) -> None:
    register = await client.post(
        "/auth/register",
        json={
            "store_name": "Tienda Users",
            "store_slug": "tienda-users",
            "admin_email": "admin-users@demo.com",
            "admin_password": "Password123!",
            "admin_first_name": "Admin",
            "admin_last_name": "Users",
        },
    )
    assert register.status_code == 201

    login = await client.post(
        "/auth/login",
        json={"email": "admin-users@demo.com", "password": "Password123!"},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    created = await client.post(
        "/users/",
        headers=headers,
        json={
            "email": "staff-users@demo.com",
            "password": "staffPassword123",
            "first_name": "Staff",
            "last_name": "Demo",
            "phone": "+5491122334455",
            "role": "staff",
        },
    )
    assert created.status_code == 201
    created_data = created.json()
    user_public_id = created_data["public_id"]

    listed = await client.get("/users/", headers=headers)
    assert listed.status_code == 200
    assert any(item["email"] == "staff-users@demo.com" for item in listed.json())

    updated = await client.patch(
        f"/users/{user_public_id}",
        headers=headers,
        json={"last_name": "Actualizado", "phone": "+5491100000000"},
    )
    assert updated.status_code == 200
    assert updated.json()["last_name"] == "Actualizado"

    deleted = await client.delete(f"/users/{user_public_id}", headers=headers)
    assert deleted.status_code == 204

    inactive_login = await client.post(
        "/auth/login",
        json={"email": "staff-users@demo.com", "password": "staffPassword123"},
    )
    assert inactive_login.status_code == 401
