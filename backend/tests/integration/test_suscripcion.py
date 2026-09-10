"""Suscripcion: aviso, gracia y suspension (Fase 6, 2026-09-10).

Antes la suscripcion era un registro informativo: cuando vencia no pasaba
nada y el dueno no la veia en ninguna pantalla.
"""

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import modules.billing.tasks as billing_tasks
import modules.notifications.tasks as tasks
from modules.billing.model import Plan, StoreSubscription
from modules.stores.model import Store
from modules.notifications.model import Notification
from modules.payments.jobs import process_outbox_batch
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
    create_service,
    register_and_login,
)
from tests.integration.test_mails_al_cliente import Buzon


async def _con_suscripcion(
    client: AsyncClient,
    session: AsyncSession,
    slug: str,
    *,
    vence_en_dias: int,
    estado: str = "active",
) -> tuple[str, str, StoreSubscription]:
    store_public_id, token = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    # store.id y store.public_id son columnas independientes con default
    # propio: la suscripcion se cuelga del id interno, que es el que ve RLS.
    store_id = (
        await session.execute(
            select(Store.id).where(Store.public_id == store_public_id)
        )
    ).scalar_one()
    plan = Plan(name=f"Plan {slug}", price=15000, currency="ARS")
    session.add(plan)
    await session.flush()
    subscription = StoreSubscription(
        store_id=store_id,
        plan_id=plan.id,
        plan_name=plan.name,
        status=estado,
        base_amount=plan.price,
        discount_amount=0,
        total_amount=plan.price,
        currency="ARS",
        current_period_start=datetime.now(timezone.utc) - timedelta(days=30),
        current_period_end=datetime.now(timezone.utc) + timedelta(days=vence_en_dias),
    )
    session.add(subscription)
    await session.commit()
    return store_public_id, token, subscription


@pytest.mark.asyncio
async def test_el_dueno_ve_su_plan_y_cuantos_dias_le_quedan(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    _store, token, _sub = await _con_suscripcion(
        client, test_session, "susc-vista", vence_en_dias=3
    )

    res = await client.get("/stores/me/subscription", headers=auth_headers(token))

    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert cuerpo["status"] == "active"
    assert cuerpo["plan_name"] == "Plan susc-vista"
    assert cuerpo["days_left"] in (2, 3)
    assert cuerpo["warn"] is True
    assert cuerpo["blocks_writes"] is False


@pytest.mark.asyncio
async def test_sin_suscripcion_no_bloquea_ni_avisa(
    client: AsyncClient,
) -> None:
    _store, token = await register_and_login(
        client, slug="susc-sin", email="susc-sin@example.com"
    )
    res = await client.get("/stores/me/subscription", headers=auth_headers(token))
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "none"
    assert res.json()["warn"] is False
    assert res.json()["blocks_writes"] is False


@pytest.mark.asyncio
async def test_el_job_avisa_una_vez_vence_y_suspende(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    monkeypatch.setattr(
        billing_tasks, "AsyncSessionFactory", lambda: _SesionCompartida(test_session)
    )
    store, token, subscription = await _con_suscripcion(
        client, test_session, "susc-ciclo", vence_en_dias=3
    )

    # 1. Aviso: una sola vez aunque el job corra dos dias seguidos.
    primera = await billing_tasks.run_subscription_lifecycle()
    assert primera["warned"] == 1
    segunda = await billing_tasks.run_subscription_lifecycle()
    assert segunda["warned"] == 0

    await process_outbox_batch(test_session)
    aviso = (
        await test_session.execute(
            select(Notification).where(Notification.type == "subscription.expiring")
        )
    ).scalar_one()
    assert "Plan susc-ciclo" in (aviso.body or "")
    assert any("vence" in asunto.lower() for _to, asunto, _cuerpo in buzon.enviados)

    # 2. Vencida: pasa a past_due y sigue operando (gracia).
    subscription.current_period_end = datetime.now(timezone.utc) - timedelta(days=1)
    await test_session.commit()
    vencida = await billing_tasks.run_subscription_lifecycle()
    assert vencida["past_due"] == 1
    assert (
        await client.get("/stores/me/subscription", headers=auth_headers(token))
    ).json()["status"] == "past_due"
    servicio = await create_service(client, token)
    assert servicio

    # 3. Gracia agotada: suspendida, se bloquean las escrituras del panel y la
    # vitrina publica desaparece; la lectura sigue.
    subscription.current_period_end = datetime.now(timezone.utc) - timedelta(days=9)
    await test_session.commit()
    agotada = await billing_tasks.run_subscription_lifecycle()
    assert agotada["suspended"] == 1

    lectura = await client.get("/stores/me", headers=auth_headers(token))
    assert lectura.status_code == 200, lectura.text
    escritura = await client.patch(
        "/stores/me", headers=auth_headers(token), json={"description": "hola"}
    )
    assert escritura.status_code == 402, escritura.text
    assert escritura.json()["error_code"] == "SUBSCRIPTION_SUSPENDED"
    alta_servicio = await client.post(
        "/services/",
        headers=auth_headers(token),
        json={"name": "Otro", "duration_minutes": 30, "price": 100},
    )
    assert alta_servicio.status_code == 402, alta_servicio.text

    publica = await client.get("/public/stores/susc-ciclo")
    assert publica.status_code == 404, publica.text

    # Cuarta corrida: nada nuevo (suspendida es estable).
    estable = await billing_tasks.run_subscription_lifecycle()
    assert estable["suspended"] == 0 and estable["past_due"] == 0
    assert store


@pytest.mark.asyncio
async def test_reasignar_un_plan_sin_fechas_conserva_el_periodo(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    """Regresion: el POST plano mandaba current_period_* en None y borraba el
    periodo vigente; el modal lo tapaba porque siempre mandaba las dos fechas."""
    from modules.users.model import User

    store_public_id, _token, subscription = await _con_suscripcion(
        client, test_session, "susc-reasignar", vence_en_dias=20
    )
    vence_original = subscription.current_period_end
    admin = (
        await test_session.execute(
            select(User).where(User.email == "susc-reasignar@example.com")
        )
    ).scalar_one()
    admin.is_global_admin = True
    otro_plan = Plan(name="Plan Oro", price=30000, currency="ARS")
    test_session.add(otro_plan)
    await test_session.commit()

    login = await client.post(
        "/auth/login",
        json={"email": "susc-reasignar@example.com", "password": "Password123!"},
    )
    assert login.status_code == 200, login.text
    su_headers = auth_headers(login.json()["access_token"])

    res = await client.post(
        f"/superadmin/stores/{store_public_id}/subscription",
        headers=su_headers,
        json={"plan_id": otro_plan.id, "base_amount": "30000"},
    )
    assert res.status_code == 200, res.text
    cuerpo = res.json()
    assert cuerpo["plan_name"] == "Plan Oro"
    assert cuerpo["current_period_end"] is not None
    assert datetime.fromisoformat(cuerpo["current_period_end"]).date() == (
        vence_original.date() if vence_original else None
    )

    # Un estado que el backend no conoce se rechaza en el schema.
    invalido = await client.post(
        f"/superadmin/stores/{store_public_id}/subscription",
        headers=su_headers,
        json={"plan_id": otro_plan.id, "status": "trialing"},
    )
    assert invalido.status_code == 422, invalido.text


class _SesionCompartida:
    """Reusa la sesion del test: el job normalmente abre la suya."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> AsyncSession:
        return self._session

    async def __aexit__(self, *args: object) -> bool:
        return False
