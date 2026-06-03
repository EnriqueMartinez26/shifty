from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from core.database import get_db
from core.models import Base
from main import app

import modules.audit.model  # noqa: F401
import modules.billing.model  # noqa: F401
import modules.stores.model  # noqa: F401
import modules.users.model  # noqa: F401

from modules.billing.model import StoreSubscription
from modules.users.model import User


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_session(test_engine):
    session_local = async_sessionmaker(bind=test_engine, expire_on_commit=False, autoflush=False)
    async with session_local() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(test_session):
    async def override_get_db():
        yield test_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http_client:
        yield http_client
    app.dependency_overrides.pop(get_db, None)


async def _register_store(client: AsyncClient, slug: str, email: str):
    response = await client.post(
        "/auth/register",
        json={
            "store_name": f"Tienda {slug}",
            "store_slug": slug,
            "admin_email": email,
            "admin_password": "password123",
            "admin_first_name": "Admin",
            "admin_last_name": slug,
        },
    )
    assert response.status_code == 201
    return response.json()


async def _login(client: AsyncClient, email: str):
    response = await client.post(
        "/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.mark.asyncio
async def test_superadmin_store_list_and_overview_include_operational_summaries(client: AsyncClient, test_session):
    await _register_store(client, "uno", "admin-uno@demo.com")
    await _register_store(client, "dos", "admin-dos@demo.com")

    result = await test_session.execute(select(User).where(User.email == "admin-uno@demo.com"))
    global_admin = result.scalar_one()
    global_admin.is_global_admin = True
    await test_session.commit()

    token = await _login(client, "admin-uno@demo.com")
    headers = {"Authorization": f"Bearer {token}"}

    stores_response = await client.get("/superadmin/stores?is_active=true", headers=headers)
    assert stores_response.status_code == 200
    stores = stores_response.json()
    assert len(stores) == 2
    assert all("admins_count" in item for item in stores)
    target_store = next(item for item in stores if item["slug"] == "uno")
    assert target_store["admins_count"] == 1
    assert target_store["users_count"] == 1
    assert target_store["has_subscription"] is False

    plan_response = await client.post(
        "/superadmin/plans",
        headers=headers,
        json={
            "name": "Plan Oro",
            "description": "Plan principal",
            "price": "25000",
            "currency": "ARS",
            "billing_interval": "monthly",
            "max_staff": 8,
            "max_services": 16,
        },
    )
    assert plan_response.status_code == 201
    plan = plan_response.json()

    subscription_response = await client.post(
        f"/superadmin/stores/{target_store['public_id']}/subscription",
        headers=headers,
        json={
            "plan_id": plan["public_id"],
            "status": "active",
            "base_amount": "25000",
            "currency": "ARS",
            "current_period_start": datetime.now(timezone.utc).isoformat(),
            "current_period_end": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        },
    )
    assert subscription_response.status_code == 200

    updated_list = await client.get("/superadmin/stores?has_subscription=true", headers=headers)
    assert updated_list.status_code == 200
    filtered = updated_list.json()
    assert len(filtered) == 1
    assert filtered[0]["slug"] == "uno"
    assert filtered[0]["current_plan_name"] == "Plan Oro"
    assert filtered[0]["subscription_status"] == "active"

    overview_response = await client.get(
        f"/superadmin/stores/{target_store['public_id']}/overview",
        headers=headers,
    )
    assert overview_response.status_code == 200
    overview = overview_response.json()
    assert overview["store"]["slug"] == "uno"
    assert overview["users"]["admins_count"] == 1
    assert overview["users"]["users_count"] == 1
    assert overview["subscription"]["plan_name"] == "Plan Oro"
    assert overview["subscription"]["billing_interval"] == "monthly"


@pytest.mark.asyncio
async def test_superadmin_can_set_receptionist_role_and_cannot_assign_subscription_to_inactive_store(client: AsyncClient, test_session):
    await _register_store(client, "central", "admin-central@demo.com")

    result = await test_session.execute(select(User).where(User.email == "admin-central@demo.com"))
    global_admin = result.scalar_one()
    global_admin.is_global_admin = True
    await test_session.commit()

    token = await _login(client, "admin-central@demo.com")
    headers = {"Authorization": f"Bearer {token}"}

    stores_response = await client.get("/superadmin/stores", headers=headers)
    store = stores_response.json()[0]

    admin_response = await client.post(
        f"/superadmin/stores/{store['public_id']}/admins",
        headers=headers,
        json={
            "email": "ops@demo.com",
            "password": "password123",
            "first_name": "Ops",
            "last_name": "Desk",
            "phone": "+5491100000000",
        },
    )
    assert admin_response.status_code == 201
    created_user = admin_response.json()

    role_response = await client.patch(
        f"/superadmin/users/{created_user['public_id']}",
        headers=headers,
        json={"role": "receptionist"},
    )
    assert role_response.status_code == 200
    assert role_response.json()["role"] == "receptionist"

    store_update = await client.patch(
        f"/superadmin/stores/{store['public_id']}",
        headers=headers,
        json={"is_active": False},
    )
    assert store_update.status_code == 200

    plan_response = await client.post(
        "/superadmin/plans",
        headers=headers,
        json={
            "name": "Plan Base",
            "description": "Plan base",
            "price": "15000",
            "currency": "ARS",
            "billing_interval": "monthly",
        },
    )
    assert plan_response.status_code == 201
    plan = plan_response.json()

    subscription_response = await client.post(
        f"/superadmin/stores/{store['public_id']}/subscription",
        headers=headers,
        json={"plan_id": plan["public_id"]},
    )
    assert subscription_response.status_code == 400
    assert "tienda inactiva" in subscription_response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_superadmin_coupon_redeem_rejects_expired_subscription(client: AsyncClient, test_session):
    await _register_store(client, "sur", "admin-sur@demo.com")

    result = await test_session.execute(select(User).where(User.email == "admin-sur@demo.com"))
    global_admin = result.scalar_one()
    global_admin.is_global_admin = True
    await test_session.commit()

    token = await _login(client, "admin-sur@demo.com")
    headers = {"Authorization": f"Bearer {token}"}

    stores_response = await client.get("/superadmin/stores", headers=headers)
    store = stores_response.json()[0]

    plan_response = await client.post(
        "/superadmin/plans",
        headers=headers,
        json={
            "name": "Plan Vencido",
            "description": "Plan test",
            "price": "10000",
            "currency": "ARS",
            "billing_interval": "monthly",
        },
    )
    plan = plan_response.json()

    subscription_response = await client.post(
        f"/superadmin/stores/{store['public_id']}/subscription",
        headers=headers,
        json={
            "plan_id": plan["public_id"],
            "status": "active",
            "base_amount": "10000",
            "currency": "ARS",
            "current_period_start": (datetime.now(timezone.utc) - timedelta(days=60)).isoformat(),
            "current_period_end": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
        },
    )
    assert subscription_response.status_code == 200

    coupon_response = await client.post(
        "/superadmin/coupons",
        headers=headers,
        json={
            "code": "WELCOME10",
            "coupon_type": "percent",
            "value": "10",
            "description": "Cupón de bienvenida",
        },
    )
    assert coupon_response.status_code == 201

    store_result = await test_session.execute(select(StoreSubscription).where(StoreSubscription.store_id == global_admin.store_id))
    assert store_result.scalar_one_or_none() is not None

    redeem_response = await client.post(
        f"/superadmin/stores/{store['public_id']}/coupons/redeem",
        headers=headers,
        json={"coupon_code": "WELCOME10"},
    )
    assert redeem_response.status_code == 400
    assert "vencida" in redeem_response.json()["detail"].lower()
