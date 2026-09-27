"""Caminos de abuso: lo que un atacante sin permisos intenta primero.

Cada test arranca con una base limpia (fixtures de
``tests/integration/conftest.py``) porque los topes y bloqueos son estado.
Los limitadores viven en Redis y estan apagados en la suite
(``tests/conftest.py``); aca se prenden contra un Redis en memoria con
``pipeline`` para ejercitar el camino real: ``core/rate_limit.py``,
``modules/otp/service.py::_consume_budget`` y el bloqueo de login de
``modules/auth/service.py``.

La rafaga concurrente sobre un mismo turno necesita Postgres (lock pesimista
y exclusion GiST): esta en
``tests/postgres/test_pg_seguridad_rafaga_y_nul.py``. Aca va la version
secuencial, que prueba la guarda de la aplicacion sin concurrencia real.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import core.rate_limit
import modules.auth.service
import modules.otp.service
from core.config import settings
from modules.auth.router import REFRESH_COOKIE
from modules.payments.model import Payment, WebhookInbox
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    add_staff_schedule,
    auth_headers,
    create_service,
    create_staff,
    register_and_login,
    seed_store_and_admin,
)
from tests.security.mundo import RedisFalso
from tests.security.rutas import firma_webhook
from tests.security.verificacion import problemas_del_error

pytestmark = pytest.mark.asyncio

SECRETO = "secreto-webhook-abuso"


@pytest.fixture
def limitador(monkeypatch: pytest.MonkeyPatch) -> RedisFalso:
    """Rate limit, presupuesto de OTP y bloqueo de login prendidos."""
    redis = RedisFalso()

    async def falso() -> RedisFalso:
        return redis

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    for modulo in (core.rate_limit, modules.otp.service, modules.auth.service):
        monkeypatch.setattr(modulo, "get_redis", falso)
    return redis


def _ip(n: int) -> dict[str, str]:
    """IP distinta por request: los topes por telefono y por cuenta no pueden
    depender de la IP, que un atacante rota sin costo."""
    return {"x-forwarded-for": f"203.0.113.{n % 250 + 1}"}


def _sin_problemas(res: Response) -> None:
    problemas = problemas_del_error(res)
    assert not problemas, f"{res.status_code}: {problemas} {res.text[:300]}"


def _error(res: Response) -> tuple[int, str, str]:
    cuerpo = res.json()
    return res.status_code, cuerpo["error_code"], cuerpo["message"]


async def _tienda_reservable(
    client: AsyncClient, slug: str
) -> tuple[str, str, str, str, datetime]:
    store, token = await register_and_login(client, slug=slug, email=f"{slug}@test.com")
    service = await create_service(client, token)
    staff = await create_staff(client, token, service, email=f"pro-{slug}@test.com")
    dia = datetime.now(timezone.utc) + timedelta(days=5)
    await add_staff_schedule(client, token, staff, target_date=dia)
    slot = dia.replace(hour=11, minute=0, second=0, microsecond=0)
    return store, token, service, staff, slot


# -- OTP ----------------------------------------------------------------------


async def test_pedir_otp_tiene_tope_por_telefono_aunque_rote_la_ip(
    client: AsyncClient, limitador: RedisFalso
) -> None:
    store, _ = await register_and_login(client, slug="abuso-otp", email="otp@test.com")
    telefono = "+5491166600001"

    def pedido(tel: str, n: int) -> dict[str, Any]:
        return {"store_public_id": store, "phone": tel, "email": f"o{n}@abuso.com"}

    for n in range(settings.OTP_MAX_REQUESTS_PER_HOUR):
        res = await client.post(
            "/public/otp/request", json=pedido(telefono, n), headers=_ip(n)
        )
        assert res.status_code == 200, (n, res.text)

    tope = await client.post(
        "/public/otp/request", json=pedido(telefono, 99), headers=_ip(99)
    )
    assert tope.status_code == 429, tope.text
    _sin_problemas(tope)
    assert "debug_code" not in tope.text
    assert telefono.lstrip("+") not in tope.text

    # El tope es del telefono, no de la tienda: otro numero sigue pudiendo.
    otro = await client.post(
        "/public/otp/request", json=pedido("+5491166600002", 1), headers=_ip(120)
    )
    assert otro.status_code == 200, otro.text


async def test_verificar_otp_agota_los_intentos_del_codigo(client: AsyncClient) -> None:
    store, _ = await register_and_login(client, slug="abuso-verif", email="v@test.com")
    telefono = "+5491166600011"
    pedido = await client.post(
        "/public/otp/request",
        json={"store_public_id": store, "phone": telefono, "email": "v@abuso.com"},
    )
    assert pedido.status_code == 200, pedido.text
    codigo = pedido.json()["debug_code"]
    incorrecto = "000000" if codigo != "000000" else "111111"

    respuestas = set()
    for _ in range(settings.OTP_MAX_ATTEMPTS):
        mal = await client.post(
            "/public/otp/verify",
            json={"store_public_id": store, "phone": telefono, "code": incorrecto},
        )
        _sin_problemas(mal)
        respuestas.add(_error(mal))
    assert len(respuestas) == 1, f"los rechazos no son identicos: {respuestas}"
    assert next(iter(respuestas))[0] in {400, 401}

    # Con los intentos agotados ni el codigo correcto entra.
    bueno = await client.post(
        "/public/otp/verify",
        json={"store_public_id": store, "phone": telefono, "code": codigo},
    )
    assert bueno.status_code == 429, bueno.text
    _sin_problemas(bueno)
    autogestion = await client.get(f"/public/client/{store}/{telefono}/appointments")
    assert autogestion.status_code == 403, autogestion.text


async def test_verificar_otp_tiene_tope_por_hora_aunque_se_pidan_codigos_nuevos(
    client: AsyncClient, limitador: RedisFalso
) -> None:
    store, _ = await register_and_login(client, slug="abuso-hora", email="h@test.com")
    telefono = "+5491166600021"
    n = 0

    async def codigo_nuevo() -> str:
        nonlocal n
        n += 1
        res = await client.post(
            "/public/otp/request",
            json={"store_public_id": store, "phone": telefono, "email": "h@abuso.com"},
            headers=_ip(n),
        )
        assert res.status_code == 200, res.text
        return cast(str, res.json()["debug_code"])

    intentos = 0
    while intentos < settings.OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR:
        codigo = await codigo_nuevo()
        incorrecto = "000000" if codigo != "000000" else "111111"
        # Menos que OTP_MAX_ATTEMPTS por codigo: lo que corta es el
        # presupuesto por hora, no el contador del codigo.
        for _ in range(min(3, settings.OTP_MAX_VERIFY_ATTEMPTS_PER_HOUR - intentos)):
            intentos += 1
            mal = await client.post(
                "/public/otp/verify",
                json={"store_public_id": store, "phone": telefono, "code": incorrecto},
                headers=_ip(100 + intentos),
            )
            assert mal.status_code in {400, 401}, mal.text

    limitador.store = {
        clave: valor
        for clave, valor in limitador.store.items()
        if not clave.startswith("otp:req:")
    }
    codigo = await codigo_nuevo()
    agotado = await client.post(
        "/public/otp/verify",
        json={"store_public_id": store, "phone": telefono, "code": codigo},
        headers=_ip(200),
    )
    assert agotado.status_code == 429, agotado.text
    _sin_problemas(agotado)


# -- login y sesiones ---------------------------------------------------------


async def test_login_bloquea_la_cuenta_tras_n_fallos_con_respuesta_neutra(
    client: AsyncClient, limitador: RedisFalso
) -> None:
    email = "victima@abuso.com"
    await seed_store_and_admin(slug="abuso-login", email=email)

    fallos = set()
    for n in range(settings.LOGIN_LOCKOUT_MAX_ATTEMPTS):
        res = await client.post(
            "/auth/login",
            json={"email": email, "password": f"Adivinanza-{n}"},
            headers=_ip(n),
        )
        _sin_problemas(res)
        fallos.add(_error(res))
    desconocido = await client.post(
        "/auth/login",
        json={"email": "nadie@abuso.com", "password": "Adivinanza-0"},
        headers=_ip(50),
    )
    # Mismo codigo, mismo error_code y mismo mensaje: el login no es un
    # oraculo de "esa cuenta existe".
    assert fallos == {_error(desconocido)}, (fallos, desconocido.text)
    assert desconocido.status_code == 401

    bloqueada = await client.post(
        "/auth/login",
        json={"email": email, "password": "Password123!"},
        headers=_ip(60),
    )
    assert bloqueada.status_code == 429, bloqueada.text
    _sin_problemas(bloqueada)
    assert "access_token" not in bloqueada.text
    assert REFRESH_COOKIE not in bloqueada.headers.get("set-cookie", "")


async def test_reuso_de_refresh_revoca_todas_las_sesiones_del_usuario(
    client: AsyncClient,
) -> None:
    email = "familia@abuso.com"
    await seed_store_and_admin(slug="abuso-refresh", email=email)

    async def dispositivo() -> tuple[str, str]:
        client.cookies.clear()
        res = await client.post(
            "/auth/login", json={"email": email, "password": "Password123!"}
        )
        assert res.status_code == 200, res.text
        refresh = res.cookies.get(REFRESH_COOKIE)
        assert refresh
        return cast(str, res.json()["access_token"]), refresh

    acceso_1, viejo_1 = await dispositivo()
    acceso_2, refresh_2 = await dispositivo()

    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE, viejo_1)
    rotacion = await client.post("/auth/refresh")
    assert rotacion.status_code == 200, rotacion.text
    nuevo_1 = rotacion.cookies.get(REFRESH_COOKIE)
    assert nuevo_1 and nuevo_1 != viejo_1

    # Senal de robo: el refresh ya rotado vuelve a aparecer.
    client.cookies.clear()
    client.cookies.set(REFRESH_COOKIE, viejo_1)
    reuso = await client.post("/auth/refresh")
    assert reuso.status_code == 401, reuso.text
    _sin_problemas(reuso)

    # Cae la familia entera: el refresh nuevo, el del otro dispositivo y los
    # access tokens emitidos antes (cuelgan de sesiones revocadas).
    for refresh in (nuevo_1, refresh_2):
        client.cookies.clear()
        client.cookies.set(REFRESH_COOKIE, refresh)
        muerto = await client.post("/auth/refresh")
        assert muerto.status_code == 401, muerto.text
    client.cookies.clear()
    for acceso in (acceso_1, acceso_2):
        me = await client.get("/me", headers=auth_headers(acceso))
        assert me.status_code == 401, me.text


# -- webhooks -----------------------------------------------------------------


async def _tienda_con_pasarela(client: AsyncClient) -> str:
    store, token = await register_and_login(
        client, slug="abuso-webhook", email="webhook@test.com"
    )
    flags = await client.put(
        "/stores/me/feature-flags", headers=auth_headers(token), json={"payments": True}
    )
    assert flags.status_code == 200, flags.text
    pasarela = await client.put(
        "/payments/gateway-config",
        headers=auth_headers(token),
        json={
            "access_token": "TEST-ACCESS-TOKEN-1234567890",
            "webhook_secret": SECRETO,
        },
    )
    assert pasarela.status_code == 200, pasarela.text
    return store


def _caso_webhook(caso: str, store: str) -> tuple[dict[str, Any], dict[str, str], Any]:
    """(params, headers, body) de cada intento de webhook forjado."""
    evento = f"evt-{caso}"
    body: Any = {"id": evento, "type": "payment", "data": {"id": evento}}
    valida = firma_webhook(evento, f"req-{caso}", secret=SECRETO)
    ahora = int(datetime.now(timezone.utc).timestamp())
    vencido = ahora - settings.MERCADOPAGO_WEBHOOK_MAX_AGE_SECONDS - 120
    casos: dict[str, tuple[dict[str, Any], dict[str, str], Any]] = {
        "firma_invalida": (
            {"store_id": store},
            {"x-request-id": "req-x", "x-signature": f"ts={ahora},v1=deadbeef"},
            body,
        ),
        "firma_con_otro_secreto": (
            {"store_id": store},
            firma_webhook(evento, "req-otro", secret="secreto-de-otra-tienda"),
            body,
        ),
        "firma_vencida": (
            {"store_id": store},
            firma_webhook(evento, "req-vencida", secret=SECRETO, ts=vencido),
            body,
        ),
        "tienda_desconocida": (
            {"store_id": "01ZZZZZZZZZZZZZZZZZZZZZZZZ"},
            valida,
            body,
        ),
        "store_id_malformado": ({"store_id": "../../etc/passwd"}, valida, body),
        "sin_store_id": ({}, valida, body),
        "sin_firma": ({"store_id": store}, {}, body),
        "cuerpo_no_json": ({"store_id": store}, valida, "esto-no-es-json"),
        "cuerpo_lista": ({"store_id": store}, valida, [1, 2, 3]),
    }
    return casos[caso]


CASOS_WEBHOOK = {
    "firma_invalida": 401,
    "firma_con_otro_secreto": 401,
    "firma_vencida": 401,
    "tienda_desconocida": 400,
    "store_id_malformado": 400,
    "sin_store_id": 400,
    "sin_firma": 400,
    "cuerpo_no_json": 400,
    "cuerpo_lista": 400,
}


async def _foto_de_pagos(session: AsyncSession) -> tuple[int, list[tuple[str, str]]]:
    inbox = (
        await session.execute(select(func.count()).select_from(WebhookInbox))
    ).scalar_one()
    pagos = (await session.execute(select(Payment.id, Payment.status))).all()
    return int(inbox), sorted((str(p), str(s)) for p, s in pagos)


@pytest.mark.parametrize("caso", sorted(CASOS_WEBHOOK))
async def test_webhook_forjado_no_toca_datos_ni_da_5xx(
    client: AsyncClient, test_session: AsyncSession, caso: str
) -> None:
    store = await _tienda_con_pasarela(client)
    antes = await _foto_de_pagos(test_session)
    params, headers, body = _caso_webhook(caso, store)
    if isinstance(body, str):
        res = await client.post(
            "/payments/webhooks/mercadopago",
            params=params,
            content=body,
            headers={**headers, "content-type": "application/json"},
        )
    else:
        res = await client.post(
            "/payments/webhooks/mercadopago", params=params, json=body, headers=headers
        )

    assert res.status_code == CASOS_WEBHOOK[caso], res.text
    _sin_problemas(res)
    test_session.expire_all()
    assert await _foto_de_pagos(test_session) == antes, "el webhook forjado escribio"


async def test_webhook_no_distingue_tienda_inexistente_de_id_malformado(
    client: AsyncClient,
) -> None:
    """Regla 7 / B2-18: el rechazo no revela si la tienda existe."""
    store = await _tienda_con_pasarela(client)
    respuestas = []
    for caso in ("tienda_desconocida", "store_id_malformado", "sin_store_id"):
        params, headers, body = _caso_webhook(caso, store)
        res = await client.post(
            "/payments/webhooks/mercadopago", params=params, json=body, headers=headers
        )
        respuestas.append(_error(res))
    assert len(set(respuestas)) == 1, respuestas


# -- idempotencia y rafaga ----------------------------------------------------


def _reserva(
    store: str,
    service: str,
    staff: str,
    slot: datetime,
    tel: str,
    nombre: str,
    clave: str,
) -> dict[str, Any]:
    return {
        "store_public_id": store,
        "service_id": service,
        "staff_id": staff,
        "starts_at": slot.isoformat(),
        "client_name": nombre,
        "client_phone": tel,
        "accepts_terms": True,
        "idempotency_key": clave,
    }


async def test_la_misma_clave_repite_la_respuesta_solo_al_mismo_cliente(
    client: AsyncClient,
) -> None:
    store, _, service, staff, slot = await _tienda_reservable(client, "abuso-idem")
    clave = "clave-compartida-0001"
    titular = _reserva(
        store, service, staff, slot, "+5491166600031", "Titular Original", clave
    )

    primera = await client.post("/public/appointments", json=titular)
    repetida = await client.post("/public/appointments", json=titular)
    assert primera.status_code == 201, primera.text
    assert repetida.status_code == 201, repetida.text
    assert repetida.json()["public_id"] == primera.json()["public_id"]

    # Otra persona que adivina (o copia) la clave no recibe la respuesta del
    # titular: ni su turno, ni su nombre, ni su telefono (AUD2-B1-06).
    intruso = _reserva(
        store,
        service,
        staff,
        slot + timedelta(hours=1),
        "+5491166600032",
        "Otra Persona",
        clave,
    )
    ajena = await client.post("/public/appointments", json=intruso)
    assert ajena.status_code in {201, 409}, ajena.text
    _sin_problemas(ajena)
    for dato in (primera.json()["public_id"], "Titular Original", "5491166600031"):
        assert dato not in ajena.text, f"la respuesta ajena trae {dato!r}"


async def test_reservas_repetidas_sobre_el_mismo_turno_dejan_pasar_una(
    client: AsyncClient,
) -> None:
    """Version secuencial (SQLite). La concurrente vive en Postgres."""
    store, _, service, staff, slot = await _tienda_reservable(client, "abuso-slot")
    codigos = []
    for n in range(8):
        res = await client.post(
            "/public/appointments",
            json=_reserva(
                store,
                service,
                staff,
                slot,
                f"+54911666001{n:02d}",
                f"Cliente {n}",
                f"rafaga-sec-{n:04d}",
            ),
        )
        _sin_problemas(res)
        codigos.append(res.status_code)
    assert codigos.count(201) == 1, codigos
    assert sorted(codigos) == [201] + [409] * 7, codigos
