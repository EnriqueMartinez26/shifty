"""Durante Mercado Pago y el SMTP ninguna conexion de la app queda "idle in transaction".

2026-09-24, F1-05 (R8-05). La reserva publica, el link del panel y los mails
del panel salian a la red con una transaccion abierta: la de las lecturas
previas o la que abre ``TenantSession.commit`` al reaplicar el contexto. En
Postgres eso es una conexion del pool (15) tomada en ``idle in transaction``
durante toda la llamada, hasta que ``idle_in_transaction_session_timeout``
(60 s) la mata. SQLite no tiene ese estado: se mira ``pg_stat_activity``
desde el rol dueno MIENTRAS la llamada externa esta en curso.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

import modules.appointments.service as appointments_service
import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    create_service,
    create_staff,
)
from tests.postgres.conftest import auth_headers, register_and_login

pytestmark = pytest.mark.postgres

_ESTADOS_APP = text(
    "SELECT state FROM pg_stat_activity "
    "WHERE usename = 'shifty_app' AND backend_type = 'client backend'"
)


class _Observador:
    """Anota el estado de las conexiones de la app en cada llamada externa."""

    def __init__(self, owner_engine: AsyncEngine) -> None:
        self.owner_engine = owner_engine
        self.muestras: list[tuple[str, list[str]]] = []

    async def mirar(self, donde: str) -> None:
        async with self.owner_engine.connect() as conn:
            estados = [fila[0] or "" for fila in (await conn.execute(_ESTADOS_APP))]
        self.muestras.append((donde, estados))

    def en_transaccion(self) -> list[tuple[str, list[str]]]:
        return [
            (donde, estados)
            for donde, estados in self.muestras
            if any(estado.startswith("idle in transaction") for estado in estados)
        ]


def _doblar_la_red(monkeypatch: pytest.MonkeyPatch, obs: _Observador) -> None:
    async def mercadopago(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await obs.mirar(f"mp {method} {path}")
        return {
            "id": f"pref-pg-f105-{len(obs.muestras)}",
            "init_point": "https://www.mercadopago.com/checkout/v1/redirect?p=pg",
        }

    async def smtp(*args: Any, **kwargs: Any) -> bool:
        await obs.mirar("smtp")
        return True

    async def mail_del_panel(*args: Any, **kwargs: Any) -> bool:
        await obs.mirar("mail del panel")
        return True

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", mercadopago)
    monkeypatch.setattr(tasks, "_send_email", smtp)
    for nombre in ("send_confirmation_email", "send_reschedule_email"):
        monkeypatch.setattr(appointments_service, nombre, mail_del_panel)


async def _tienda_con_cobros(
    client: AsyncClient, app_sessions: async_sessionmaker[AsyncSession], slug: str
) -> tuple[str, str, str, str, datetime]:
    store, token = await register_and_login(
        client, app_sessions, slug=slug, email=f"{slug}@demo.com"
    )
    headers = auth_headers(token)
    for metodo, ruta, cuerpo in (
        ("PATCH", "/stores/me", {"deposit_policy": "La sena se descuenta del total."}),
        ("PUT", "/stores/me/feature-flags", {"payments": True}),
        (
            "PUT",
            "/payments/gateway-config",
            {
                "access_token": "TEST-ACCESS-TOKEN-1234567890",
                "public_key": "TEST-PUBLIC-KEY",
                "webhook_secret": "secret-demo",
            },
        ),
    ):
        res = await client.request(metodo, ruta, headers=headers, json=cuerpo)
        assert res.status_code == 200, res.text
    servicio = await create_service(
        client, token, deposit_mode="required", deposit_type="percent", deposit_amount=30
    )
    staff = await create_staff(client, token, servicio, email=f"pro-{slug}@demo.com")
    dia = datetime.now(timezone.utc) + timedelta(days=6)
    await add_staff_schedule(client, token, staff, target_date=dia)
    return store, token, servicio, staff, dia


@pytest.mark.asyncio
async def test_ninguna_llamada_externa_corre_con_la_conexion_en_transaccion(
    client: AsyncClient,
    app_sessions: async_sessionmaker[AsyncSession],
    owner_engine: AsyncEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    obs = _Observador(owner_engine)
    _doblar_la_red(monkeypatch, obs)
    store, token, servicio, staff, dia = await _tienda_con_cobros(
        client, app_sessions, "pg-f105"
    )
    obs.muestras.clear()

    # Reserva publica con sena: link de MP + mail "reserva registrada".
    reserva = await client.post(
        "/public/appointments",
        json={
            "store_public_id": store,
            "service_id": servicio,
            "staff_id": staff,
            "starts_at": dia.replace(hour=10, minute=0, second=0, microsecond=0).isoformat(),
            "client_name": "Cliente PG",
            "client_email": "cliente-pg@demo.com",
            "client_phone": "+5491155577001",
            "payment_method": "mercadopago",
            "accepts_terms": True,
        },
    )
    assert reserva.status_code == 201, reserva.text

    # Turno del panel (mail de confirmacion) y su link de pago (MP).
    panel = await client.post(
        "/appointments/",
        headers=auth_headers(token),
        json={
            "service_id": servicio,
            "staff_id": staff,
            "starts_at": dia.replace(hour=11, minute=0, second=0, microsecond=0).isoformat(),
            "idempotency_key": "pg-f105-panel-turno",
        },
    )
    assert panel.status_code == 201, panel.text
    link = await client.post(
        f"/payments/preferences/{panel.json()['public_id']}",
        headers=auth_headers(token),
    )
    assert link.status_code == 200, link.text

    lugares = {donde.split(" ")[0] for donde, _ in obs.muestras}
    assert {"mp", "smtp", "mail"} <= lugares, obs.muestras
    # La consulta ve a la app: sin esto una vista sin permisos pasaria vacia.
    assert all(estados for _, estados in obs.muestras), obs.muestras
    assert obs.en_transaccion() == [], (
        f"conexion de la app en transaccion durante la red: {obs.en_transaccion()}"
    )
