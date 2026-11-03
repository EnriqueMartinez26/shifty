"""La conexion de Mercado Pago que no se renueva queda marcada como rota.

Issue #279 (2026-11-02): el token OAuth de MP solo se renueva despues de un
401. Si MP rechaza la renovacion (la tienda revoco la app, el refresh token
vencio), se levantaba un ``RuntimeError``: la reserva publica respondia 502
``PAYMENT_LINK_CREATION_FAILED`` con un warning de structlog y nada mas. Sin
evento a Sentry ni aviso al dueno, y como ``auto`` prefiere MP para una sena
obligatoria, toda reserva con sena se frenaba aunque la tienda tuviera
WhatsApp.

Ahora el rechazo marca la conexion (``connection_broken_at``) una sola vez:
aviso "Reconecta Mercado Pago" al panel y por mail, un evento a Sentry por
tienda (``OncePer``) y ``gateway_has_usable_token`` la da por no usable, asi
que la sena pasa a WhatsApp si la tienda lo tiene. Un callback de OAuth
exitoso la limpia. Una falla transitoria del endpoint de tokens no marca nada.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value

import modules.notifications.tasks as tasks
import modules.payments.service as payments_service
from core.config import settings
from core.crypto import decrypt_secret, encrypt_secret
from core.observability import OncePer
from modules.appointments.model import Appointment
from modules.notifications.model import Notification, NotificationType
from modules.payments.jobs import (
    expire_unpaid_appointments,
    persist_gateway_refresh,
    process_outbox_batch,
)
from modules.payments.model import OutboxMessage, PaymentGatewayConfig
from modules.payments.service import refresh_mercadopago_oauth_connection
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    auth_headers,
)
from tests.integration.test_mails_al_cliente import Buzon
from tests.integration.test_payments_hardening_and_legal import _stub_preference
from tests.integration.test_sena_por_mp_o_whatsapp import (
    _cobro,
    _mp_prohibido,
    _reservar,
    _Tienda,
    _tienda,
    _whatsapp,
)

TOKEN_VENCIDO = "TEST-ACCESS-TOKEN-1234567890"
LINK_SANO = "https://www.mercadopago.com/checkout/v1/redirect?pref=hardening"


def _oauth_configurado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setattr(settings, "MERCADOPAGO_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setattr(
        settings,
        "MERCADOPAGO_OAUTH_REDIRECT_URI",
        "https://api.shifty.test/payments/mercadopago/oauth/callback",
    )


async def _store_id(session: AsyncSession, t: _Tienda) -> str:
    return str(
        (
            await session.execute(select(Store.id).where(Store.public_id == t.store))
        ).scalar_one()
    )


async def _por_oauth(session: AsyncSession, t: _Tienda) -> str:
    """La config de la tienda pasa a OAuth con refresh token. Devuelve store_id."""
    store_id = await _store_id(session, t)
    await session.execute(
        update(PaymentGatewayConfig)
        .where(PaymentGatewayConfig.store_id == store_id)
        .values(
            connection_mode="oauth",
            encrypted_refresh_token=encrypt_secret("TG-REFRESH-1"),
        )
    )
    await session.commit()
    return store_id


async def _config(session: AsyncSession, store_id: str) -> PaymentGatewayConfig:
    session.expire_all()
    return (
        await session.execute(
            select(PaymentGatewayConfig).where(
                PaymentGatewayConfig.store_id == store_id
            )
        )
    ).scalar_one()


async def _marcar_rota(session: AsyncSession, store_id: str) -> None:
    await session.execute(
        update(PaymentGatewayConfig)
        .where(PaymentGatewayConfig.store_id == store_id)
        .values(connection_broken_at=datetime.now(timezone.utc))
    )
    await session.commit()


async def _avisos(session: AsyncSession) -> list[OutboxMessage]:
    session.expire_all()
    return list(
        (
            await session.execute(
                select(OutboxMessage).where(
                    OutboxMessage.event_type
                    == NotificationType.MERCADOPAGO_CONNECTION_BROKEN.value
                )
            )
        )
        .scalars()
        .all()
    )


def _mp_con_token_vencido(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """La API de MP responde 401 al token guardado (anota cada llamada)."""
    llamadas: list[str] = []

    async def api(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        llamadas.append(path)
        raise payments_service.MercadoPagoAPIError("token vencido", status_code=401)

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", api)
    return llamadas


def _endpoint_de_tokens(
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    body: dict[str, Any] | None = None,
) -> None:
    """``POST /oauth/token`` de MP responde ``status_code`` (por la red real
    del modulo: se prueba la clasificacion del error, no un doble de ella).
    Sin ``body``, el ``invalid_grant`` de un refresh token vencido o revocado."""
    cuerpo = body or {"error": "invalid_grant", "message": "invalid refresh_token"}

    async def enviar(method: str, url: str, **_: Any) -> httpx.Response:
        assert url.endswith("/oauth/token"), url
        return httpx.Response(
            status_code, json=cuerpo, request=httpx.Request(method, url)
        )

    monkeypatch.setattr(payments_service, "_send_to_mercadopago", enviar)


def _sentry(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    eventos: list[dict[str, Any]] = []

    def reportar(exc: BaseException, **contexto: Any) -> None:
        eventos.append({"tipo": type(exc).__name__, **contexto})

    monkeypatch.setattr(payments_service, "report_exception", reportar)
    return eventos


# ---------------------------------------------------------------------------
# (a) El rechazo de la renovacion marca la conexion y avisa una sola vez
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_un_refresh_rechazado_marca_la_conexion_rota_y_avisa_una_vez(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    _oauth_configurado(monkeypatch)
    eventos = _sentry(monkeypatch)
    t = await _tienda(client, "mp-rota-aviso", mercadopago=True)
    store_id = await _por_oauth(test_session, t)
    _mp_con_token_vencido(monkeypatch)
    _endpoint_de_tokens(monkeypatch, 400)

    # La reserva que se topa con el rechazo falla como hoy (502)...
    res = await _reservar(client, t, hora=10, metodo="auto")
    assert res.status_code == 502, res.text
    assert res.json()["error_code"] == "PAYMENT_LINK_CREATION_FAILED"

    # ...pero la conexion quedo marcada, con un aviso y un evento a Sentry.
    assert (await _config(test_session, store_id)).connection_broken_at is not None
    avisos = await _avisos(test_session)
    assert [a.store_id for a in avisos] == [store_id]
    assert [e["store_id"] for e in eventos] == [store_id]
    assert eventos[0]["tipo"] == "MercadoPagoConnectionBroken"

    # Otro rechazo (el boton "Renovar" del panel) no repite aviso ni Sentry.
    renovar = await client.post(
        "/payments/mercadopago/oauth/refresh", headers=auth_headers(t.token)
    )
    assert renovar.status_code == 409, renovar.text
    assert renovar.json()["error_code"] == "MERCADOPAGO_REFRESH_FAILED"
    assert len(await _avisos(test_session)) == 1
    assert len(eventos) == 1

    # El aviso llega al panel y por mail al admin.
    await process_outbox_batch(test_session)
    aviso = (
        await test_session.execute(
            select(Notification).where(
                Notification.type
                == NotificationType.MERCADOPAGO_CONNECTION_BROKEN.value
            )
        )
    ).scalar_one()
    assert aviso.title == "Reconectá Mercado Pago"
    assert "WhatsApp" in (aviso.body or "")
    assert [(d, asunto) for d, asunto, _c in buzon.enviados] == [
        ("mp-rota-aviso@t.com", "Shifty - Reconectá Mercado Pago")
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [408, 429, 500, 503])
async def test_una_falla_transitoria_del_refresh_no_marca_la_conexion(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
) -> None:
    _oauth_configurado(monkeypatch)
    eventos = _sentry(monkeypatch)
    t = await _tienda(client, f"mp-rota-transitoria-{status_code}", mercadopago=True)
    store_id = await _por_oauth(test_session, t)
    _mp_con_token_vencido(monkeypatch)
    _endpoint_de_tokens(monkeypatch, status_code)

    res = await _reservar(client, t, hora=10, metodo="auto")

    assert res.status_code == 502, res.text
    assert (await _config(test_session, store_id)).connection_broken_at is None
    assert await _avisos(test_session) == []
    assert eventos == []


# ---------------------------------------------------------------------------
# (b) Con la conexion rota la sena obligatoria pasa a WhatsApp
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_con_la_conexion_rota_la_sena_obligatoria_pasa_a_whatsapp(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, "mp-rota-whatsapp", mercadopago=True)
    store_id = await _por_oauth(test_session, t)
    await _marcar_rota(test_session, store_id)
    llamadas = _mp_prohibido(monkeypatch)

    res = await _reservar(client, t, metodo="auto")

    assert res.status_code == 201, res.text
    assert res.json()["deposit_channel"] == "whatsapp"
    assert res.json()["payment_link"] is None
    cobro = await _cobro(test_session, res.json()["public_id"])
    assert cobro is not None and cobro.provider == "manual"
    assert llamadas == []


@pytest.mark.asyncio
async def test_con_la_conexion_rota_y_sin_whatsapp_la_sena_sigue_sin_canal(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    t = await _tienda(client, "mp-rota-sin-whatsapp", mercadopago=True)
    await _whatsapp(client, t.token, None)
    store_id = await _por_oauth(test_session, t)
    await _marcar_rota(test_session, store_id)
    llamadas = _mp_prohibido(monkeypatch)

    res = await _reservar(client, t, metodo="auto")

    # Falla igual, ahora antes de escribir nada (el 409 de "sin canal").
    assert res.status_code == 409, res.text
    assert res.json()["error_code"] == "DEPOSIT_CHANNEL_UNAVAILABLE"
    test_session.expire_all()
    assert list((await test_session.execute(select(Appointment))).scalars()) == []
    assert llamadas == []


# ---------------------------------------------------------------------------
# (c) Un callback de OAuth exitoso limpia la marca
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconectar_por_oauth_limpia_la_conexion_rota(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _oauth_configurado(monkeypatch)
    t = await _tienda(client, "mp-rota-reconecta", mercadopago=True)
    store_id = await _por_oauth(test_session, t)
    await _marcar_rota(test_session, store_id)

    async def canje(*, code: str, code_verifier: str) -> dict[str, str]:
        return {
            "access_token": "APP_USR-reconectado",
            "refresh_token": "TG-reconectado",
            "public_key": "APP_USR-public",
            "user_id": "123456",
        }

    monkeypatch.setattr(payments_service, "exchange_mercadopago_oauth_code", canje)
    start = await client.post(
        "/payments/mercadopago/oauth/start", headers=auth_headers(t.token)
    )
    assert start.status_code == 200, start.text
    state = start.json()["auth_url"].split("state=")[1].split("&", 1)[0]
    callback = await client.get(
        f"/payments/mercadopago/oauth/callback?code=oauth-code-demo&state={state}"
    )
    assert callback.status_code == 303, callback.text
    assert "mercadopago=connected" in callback.headers["location"]

    assert (await _config(test_session, store_id)).connection_broken_at is None
    _stub_preference(monkeypatch)
    res = await _reservar(client, t, metodo="auto")
    assert res.status_code == 201, res.text
    assert res.json()["deposit_channel"] == "mercadopago"
    assert res.json()["payment_link"] == LINK_SANO


# ---------------------------------------------------------------------------
# (d) El camino sano no cambia
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_un_refresh_exitoso_sigue_por_mercado_pago_sin_marca_ni_aviso(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _oauth_configurado(monkeypatch)
    eventos = _sentry(monkeypatch)
    t = await _tienda(client, "mp-sana-refresh", mercadopago=True)
    store_id = await _por_oauth(test_session, t)
    tokens: list[str] = []

    async def api(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        tokens.append(access_token)
        if access_token == TOKEN_VENCIDO:
            raise payments_service.MercadoPagoAPIError("vencido", status_code=401)
        return {"id": "pref-hardening", "init_point": LINK_SANO}

    async def token_oauth(form_data: dict[str, str]) -> dict[str, Any]:
        assert form_data["grant_type"] == "refresh_token"
        return {"access_token": "APP_USR-nuevo", "refresh_token": "TG-REFRESH-2"}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", api)
    monkeypatch.setattr(
        payments_service, "_mercadopago_oauth_token_request", token_oauth
    )

    res = await _reservar(client, t, metodo="auto")

    assert res.status_code == 201, res.text
    assert res.json()["deposit_channel"] == "mercadopago"
    assert res.json()["payment_link"] == LINK_SANO
    assert tokens == [TOKEN_VENCIDO, "APP_USR-nuevo"]
    assert (await _config(test_session, store_id)).connection_broken_at is None
    assert await _avisos(test_session) == []
    assert eventos == []


# ---------------------------------------------------------------------------
# Rechazos que no son de la tienda: Sentry, sin marca ni aviso
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "body"),
    [
        (400, {"error": "invalid_client", "message": "invalid client_secret"}),
        (403, {"error": "unauthorized_client"}),
        (401, {"message": "sin codigo de error"}),
    ],
)
async def test_un_rechazo_de_la_plataforma_avisa_a_sentry_sin_marcar_la_tienda(
    client: AsyncClient,
    test_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    status_code: int,
    body: dict[str, Any],
) -> None:
    """Credenciales de la app (``invalid_client`` y otros 4xx): reconectar la
    tienda no lo arregla, asi que no se le avisa ni se marca su conexion."""
    _oauth_configurado(monkeypatch)
    eventos = _sentry(monkeypatch)
    monkeypatch.setattr(payments_service, "_rechazos_de_la_plataforma", OncePer(3600))
    t = await _tienda(client, f"mp-plataforma-{status_code}", mercadopago=True)
    store_id = await _por_oauth(test_session, t)
    _mp_con_token_vencido(monkeypatch)
    _endpoint_de_tokens(monkeypatch, status_code, body)

    res = await _reservar(client, t, hora=10, metodo="auto")

    assert res.status_code == 502, res.text
    assert (await _config(test_session, store_id)).connection_broken_at is None
    assert await _avisos(test_session) == []
    assert [e["tipo"] for e in eventos] == ["MercadoPagoOAuthPlatformRejected"]


# ---------------------------------------------------------------------------
# Dos refresh a la vez con el mismo refresh token (MP lo rota)
# ---------------------------------------------------------------------------


async def _token_renovado(form_data: dict[str, str]) -> dict[str, Any]:
    assert form_data["grant_type"] == "refresh_token"
    return {"access_token": "APP_USR-nuevo", "refresh_token": "TG-REFRESH-2"}


async def _refrescar(session: AsyncSession, config: PaymentGatewayConfig) -> None:
    """El refresh de un 401 del webhook o de un job: persiste en su propia
    transaccion corta (``persist_gateway_refresh``)."""
    await refresh_mercadopago_oauth_connection(
        session, config=config, persist=partial(persist_gateway_refresh, session)
    )


@pytest.mark.asyncio
async def test_el_refresh_que_pierde_la_carrera_no_marca_la_conexion_renovada(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El ganador ya commiteo R2; el perdedor manda R1 y MP responde
    ``invalid_grant``. La conexion esta sana: ni marca ni aviso."""
    _oauth_configurado(monkeypatch)
    eventos = _sentry(monkeypatch)
    t = await _tienda(client, "mp-carrera-gana-primero", mercadopago=True)
    store_id = await _por_oauth(test_session, t)
    config = await _config(test_session, store_id)
    r1 = config.encrypted_refresh_token
    pedido_real = payments_service._mercadopago_oauth_token_request

    monkeypatch.setattr(
        payments_service, "_mercadopago_oauth_token_request", _token_renovado
    )
    await _refrescar(test_session, config)

    # El perdedor leyo la fila antes de la rotacion.
    set_committed_value(config, "encrypted_refresh_token", r1)
    monkeypatch.setattr(
        payments_service, "_mercadopago_oauth_token_request", pedido_real
    )
    _endpoint_de_tokens(monkeypatch, 400)
    with pytest.raises(payments_service.MercadoPagoOAuthRejectedError):
        await _refrescar(test_session, config)

    fila = await _config(test_session, store_id)
    assert fila.connection_broken_at is None
    assert decrypt_secret(fila.encrypted_refresh_token or "") == "TG-REFRESH-2"
    assert await _avisos(test_session) == []
    assert eventos == []


@pytest.mark.asyncio
async def test_el_refresh_que_gana_limpia_la_marca_del_que_perdio(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """El perdedor marca antes de que el ganador escriba R2: el ganador, que
    leyo la fila sin marca, la limpia igual, y el aviso ya no sale."""
    buzon = Buzon()
    monkeypatch.setattr(tasks, "_send_email", buzon)
    _oauth_configurado(monkeypatch)
    t = await _tienda(client, "mp-carrera-marca-primero", mercadopago=True)
    store_id = await _por_oauth(test_session, t)
    config = await _config(test_session, store_id)

    _endpoint_de_tokens(monkeypatch, 400)
    with pytest.raises(payments_service.MercadoPagoOAuthRejectedError):
        await _refrescar(test_session, config)
    assert (await _config(test_session, store_id)).connection_broken_at is not None
    assert len(await _avisos(test_session)) == 1

    # El ganador leyo la fila antes de la marca.
    config = await _config(test_session, store_id)
    set_committed_value(config, "connection_broken_at", None)
    monkeypatch.setattr(
        payments_service, "_mercadopago_oauth_token_request", _token_renovado
    )
    await _refrescar(test_session, config)

    assert (await _config(test_session, store_id)).connection_broken_at is None
    await process_outbox_batch(test_session)
    test_session.expire_all()
    avisos = (
        await test_session.execute(
            select(Notification).where(
                Notification.type
                == NotificationType.MERCADOPAGO_CONNECTION_BROKEN.value
            )
        )
    ).scalars()
    assert list(avisos) == []
    assert buzon.enviados == []


# ---------------------------------------------------------------------------
# Si marcar falla, la reserva se compensa igual
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_si_la_marca_falla_la_reserva_se_compensa_igual(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    _oauth_configurado(monkeypatch)
    t = await _tienda(client, "mp-marca-falla", mercadopago=True)
    store_id = await _por_oauth(test_session, t)
    _mp_con_token_vencido(monkeypatch)
    _endpoint_de_tokens(monkeypatch, 400)

    async def marca_que_rompe(
        db: AsyncSession, config: PaymentGatewayConfig, *_: Any
    ) -> bool:
        # Un error de la base en medio de la marca (aca, una fila duplicada).
        db.add(
            PaymentGatewayConfig(
                store_id=config.store_id,
                provider="mercadopago",
                encrypted_access_token="duplicada",
            )
        )
        await db.flush()
        return True

    monkeypatch.setattr(payments_service, "_claim_broken_mark", marca_que_rompe)

    res = await _reservar(client, t, hora=10, metodo="auto")

    assert res.status_code == 502, res.text
    assert res.json()["error_code"] == "PAYMENT_LINK_CREATION_FAILED"
    test_session.expire_all()
    assert list((await test_session.execute(select(Appointment))).scalars()) == []
    assert (await _config(test_session, store_id)).connection_broken_at is None
    assert await _avisos(test_session) == []


# ---------------------------------------------------------------------------
# Otros caminos que limpian una marca existente
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_un_refresh_exitoso_del_job_limpia_una_marca_existente(
    client: AsyncClient, test_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """401 -> refresh exitoso en el job de retenciones, que persiste con
    ``persist_gateway_refresh``. El job vence el turno como siempre."""
    monkeypatch.setattr(tasks, "_send_email", Buzon())
    _oauth_configurado(monkeypatch)
    _stub_preference(monkeypatch)
    t = await _tienda(client, "mp-rota-job", mercadopago=True)
    reserva = await _reservar(client, t, metodo="mercadopago")
    assert reserva.status_code == 201, reserva.text
    store_id = await _por_oauth(test_session, t)
    await _marcar_rota(test_session, store_id)
    await test_session.execute(
        update(Appointment).values(
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=5)
        )
    )
    await test_session.commit()

    async def api(
        access_token: str,
        *,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if access_token == TOKEN_VENCIDO:
            raise payments_service.MercadoPagoAPIError("vencido", status_code=401)
        return {"results": []}

    monkeypatch.setattr(payments_service, "_mercadopago_api_request", api)
    monkeypatch.setattr(
        payments_service, "_mercadopago_oauth_token_request", _token_renovado
    )

    stats = await expire_unpaid_appointments(test_session)

    assert stats["expired"] == 1, stats
    assert (await _config(test_session, store_id)).connection_broken_at is None


@pytest.mark.asyncio
async def test_cargar_un_token_manual_limpia_la_marca(
    client: AsyncClient, test_session: AsyncSession
) -> None:
    t = await _tienda(client, "mp-rota-manual", mercadopago=True)
    store_id = await _store_id(test_session, t)
    await _marcar_rota(test_session, store_id)

    res = await client.put(
        "/payments/gateway-config",
        headers=auth_headers(t.token),
        json={"access_token": "TEST-ACCESS-TOKEN-NUEVO-0987654321"},
    )

    assert res.status_code == 200, res.text
    assert (await _config(test_session, store_id)).connection_broken_at is None
