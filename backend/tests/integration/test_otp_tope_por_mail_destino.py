"""El OTP no sirve para bombardear una casilla: tope de mails por DESTINO.

Hallazgo de auditoria (2026-10-03): ``/public/otp/request`` manda un mail a
la direccion que tipea un anonimo. Lo frenaban tres cubetas: por IP, por
tienda + telefono (``enforce_rate_limit``) y el presupuesto acumulado por
telefono (``OTP_MAX_REQUESTS_PER_HOUR``). Ninguna miraba a QUIEN se le
escribe: rotando telefonos e IPs cualquiera usaba Shifty para llenar de mails
una casilla ajena, y las quejas de esa casilla queman la reputacion del
dominio de envio (SES suspende la cuenta con una tasa de quejas alta).

Ahora cada mail del OTP (el codigo y el aviso sin codigo de AUD2-B4-05)
consume la cuota de SU destino real: el email tipeado o el de la ficha del
cliente, segun adonde vaya. Pasado el tope, ese mail no sale y la respuesta
es la misma, con la misma forma: el tope no puede decir si la casilla existe,
si el telefono es cliente ni si la casilla ya recibio otros codigos.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.testing import capture_logs

import core.rate_limit as rate_limit
import modules.notifications.tasks as tasks
import modules.otp.service as otp_service
from core.config import settings
from core.exceptions import AppException
from modules.otp.model import OtpVerification
from modules.otp.service import OtpService
from modules.stores.model import Store
from modules.users.model import User, UserRole
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)
from tests.integration.test_otp_por_email import Cola

VICTIMA = "victima@example.com"
TELEFONO_CLIENTE = "5491155551234"
EMAIL_CLIENTE = "cliente-real@example.com"


class _RedisContador:
    """INCR/EXPIRE en memoria con las claves a la vista."""

    def __init__(self) -> None:
        self.valores: dict[str, int] = {}

    def pipeline(self, transaction: bool = True) -> "_Pipeline":
        return _Pipeline(self)


class _Pipeline:
    def __init__(self, redis: _RedisContador) -> None:
        self.redis = redis
        self.ops: list[tuple[str, str]] = []

    def incr(self, key: str) -> None:
        self.ops.append(("incr", key))

    def expire(self, key: str, seconds: int) -> None:
        self.ops.append(("expire", key))

    async def execute(self) -> list[Any]:
        resultados: list[Any] = []
        for op, key in self.ops:
            if op == "incr":
                self.redis.valores[key] = self.redis.valores.get(key, 0) + 1
                resultados.append(self.redis.valores[key])
            else:
                resultados.append(True)
        return resultados


@pytest.fixture
def redis_de_estado(monkeypatch: pytest.MonkeyPatch) -> _RedisContador:
    """Un solo Redis de estado para el limitador y el presupuesto del OTP."""
    redis = _RedisContador()

    async def fake_get_redis() -> _RedisContador:
        return redis

    monkeypatch.setattr(rate_limit, "get_redis", fake_get_redis)
    monkeypatch.setattr(otp_service, "get_redis", fake_get_redis)
    return redis


@pytest.fixture
def cola(monkeypatch: pytest.MonkeyPatch) -> Cola:
    encolados = Cola()
    monkeypatch.setattr(tasks, "send_otp_email", encolados)
    return encolados


def _con_limites(monkeypatch: pytest.MonkeyPatch) -> None:
    # Despues del alta de la tienda: el login de ``register_and_login`` no
    # tiene que gastar cuotas de este test.
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "TRUST_PROXY_HEADERS", True)


async def _pedir(
    client: AsyncClient, tienda: str, telefono: str, email: str, ip: str
) -> tuple[int, dict[str, Any]]:
    respuesta = await client.post(
        "/public/otp/request",
        headers={"x-raw-response": "false", "X-Forwarded-For": ip},
        json={
            "store_public_id": tienda,
            "phone": f"+{telefono}",
            "channel": "email",
            "email": email,
        },
    )
    cuerpo = respuesta.json()
    return respuesta.status_code, cuerpo


def _forma(cuerpo: dict[str, Any]) -> object:
    """La forma del sobre, sin los valores que cambian por pedido."""
    data = cuerpo.get("data", {})
    return sorted(cuerpo), sorted(data) if isinstance(data, dict) else data


async def _tienda_con_cliente(
    client: AsyncClient, session: AsyncSession, slug: str
) -> str:
    publica, _ = await register_and_login(
        client, slug=slug, email=f"{slug}@example.com"
    )
    store_id = await session.scalar(select(Store.id).where(Store.public_id == publica))
    assert store_id is not None
    session.add(
        User(
            email=EMAIL_CLIENTE,
            hashed_password="!",
            role=UserRole.CLIENT.value,
            store_id=store_id,
            phone=TELEFONO_CLIENTE,
            full_name="Cliente real",
        )
    )
    await session.commit()
    return publica


@pytest.mark.asyncio
async def test_el_tope_corta_por_destino_aunque_roten_telefono_e_ip(
    client: AsyncClient,
    redis_de_estado: _RedisContador,
    cola: Cola,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tienda, _ = await register_and_login(
        client, slug="otp-tope-destino", email="otp-tope-destino@example.com"
    )
    _con_limites(monkeypatch)
    tope = settings.OTP_MAX_MAILS_PER_DESTINATION_PER_HOUR

    respuestas = [
        await _pedir(client, tienda, f"54911600000{n:02d}", VICTIMA, f"203.0.113.{n}")
        for n in range(tope + 3)
    ]

    # Cada pedido usa un telefono y una IP nuevos: ninguna cubeta vieja corta.
    assert [status for status, _ in respuestas] == [200] * (tope + 3)
    assert [d for d, _, _ in cola.enviados] == [VICTIMA] * tope, (
        "la casilla tipeada recibio mas mails que el tope por destino"
    )
    # Neutro: el pedido que paso el tope responde lo mismo que el primero.
    assert {repr(_forma(c)) for _, c in respuestas} == {repr(_forma(respuestas[0][1]))}


@pytest.mark.asyncio
async def test_el_tope_diario_corta_aunque_la_hora_deje_pasar(
    client: AsyncClient,
    redis_de_estado: _RedisContador,
    cola: Cola,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tienda, _ = await register_and_login(
        client, slug="otp-tope-dia", email="otp-tope-dia@example.com"
    )
    _con_limites(monkeypatch)
    monkeypatch.setattr(settings, "OTP_MAX_MAILS_PER_DESTINATION_PER_HOUR", 100)
    tope_diario = settings.OTP_MAX_MAILS_PER_DESTINATION_PER_DAY

    for n in range(tope_diario + 2):
        status, _ = await _pedir(
            client, tienda, f"54911800000{n:02d}", VICTIMA, f"203.0.113.{100 + n}"
        )
        assert status == 200

    assert len(cola.enviados) == tope_diario


@pytest.mark.asyncio
async def test_el_tope_cuenta_el_destino_real_del_codigo(
    client: AsyncClient,
    test_session: AsyncSession,
    redis_de_estado: _RedisContador,
    cola: Cola,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El telefono es de un cliente: el codigo va a SU email, no al tipeado.

    El presupuesto por telefono es por tienda, asi que el mismo cliente en dos
    tiendas junta mas pedidos que el tope; los mails al email de la ficha
    tienen que cortar igual, y cada email tipeado (distinto en cada pedido)
    sigue recibiendo su aviso sin codigo.
    """
    tiendas = [
        await _tienda_con_cliente(client, test_session, "otp-tope-ficha-a"),
        await _tienda_con_cliente(client, test_session, "otp-tope-ficha-b"),
    ]
    _con_limites(monkeypatch)
    tope = settings.OTP_MAX_MAILS_PER_DESTINATION_PER_HOUR
    pedidos = tope + 1

    for n in range(pedidos):
        status, _ = await _pedir(
            client,
            tiendas[n % 2],
            TELEFONO_CLIENTE,
            f"tipeado-{n}@example.com",
            f"198.51.100.{n}",
        )
        assert status == 200

    al_cliente = [d for d, _, _ in cola.enviados if d == EMAIL_CLIENTE]
    tipeados = [d for d, _, _ in cola.enviados if d.startswith("tipeado-")]
    assert len(al_cliente) == tope, "el email de la ficha paso el tope por destino"
    assert len(tipeados) == pedidos, "el tope de un destino corto a otro"


@pytest.mark.asyncio
async def test_la_clave_del_tope_no_lleva_el_email_crudo(
    client: AsyncClient,
    redis_de_estado: _RedisContador,
    cola: Cola,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tienda, _ = await register_and_login(
        client, slug="otp-tope-clave", email="otp-tope-clave@example.com"
    )
    _con_limites(monkeypatch)
    monkeypatch.setattr(settings, "OTP_MAX_MAILS_PER_DESTINATION_PER_HOUR", 1)

    with capture_logs() as eventos:
        for n in range(2):
            status, _ = await _pedir(
                client, tienda, f"549116000009{n}", "Victima@Example.com", "203.0.113.9"
            )
            assert status == 200

    # El segundo pedido paso el tope: el log lo registra sin el buzon.
    assert any(e["event"] == "otp_mail_destination_capped" for e in eventos)
    for evento in eventos:
        assert "victima" not in repr(evento).lower(), evento
    claves = list(redis_de_estado.valores)
    del_destino = [c for c in claves if "otp:mail-destination" in c]
    assert len(del_destino) == 2, claves  # ventana de una hora y de un dia
    for clave in claves:
        assert "victima" not in clave.lower(), clave
        assert "example.com" not in clave.lower(), clave


@pytest.mark.asyncio
async def test_el_mismo_destino_en_mayusculas_comparte_la_cuota(
    client: AsyncClient,
    redis_de_estado: _RedisContador,
    cola: Cola,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tienda, _ = await register_and_login(
        client, slug="otp-tope-mayus", email="otp-tope-mayus@example.com"
    )
    _con_limites(monkeypatch)
    tope = settings.OTP_MAX_MAILS_PER_DESTINATION_PER_HOUR
    variantes = ["VICTIMA@example.com", " victima@EXAMPLE.com", "Victima@example.com"]

    for n in range(tope + 2):
        await _pedir(
            client,
            tienda,
            f"54911700000{n:02d}",
            variantes[n % len(variantes)],
            f"192.0.2.{n}",
        )

    assert len(cola.enviados) == tope


@pytest.mark.asyncio
async def test_sin_redis_en_produccion_el_tope_falla_cerrado(
    test_session: AsyncSession,
    redis_de_estado: _RedisContador,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El presupuesto por telefono responde; el limitador de destino no.

    Sin Redis, el tope por destino no puede decir que el mail esta dentro de
    la cuota: 503 como ``enforce_rate_limit`` con politica ``otp``, antes de
    guardar el codigo (no invalida el codigo vivo de nadie) y sin encolar.
    """

    async def caido(*_args: object, **_kwargs: object) -> int:
        raise RedisConnectionError("redis down")

    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(settings, "RATE_LIMIT_FAIL_CLOSED", True)
    monkeypatch.setattr(rate_limit, "_hit_rate_limit", caido)
    encolados: list[tuple[str, str, str]] = []

    with pytest.raises(AppException) as exc_info:
        await OtpService(test_session).request_code(
            store_id="tienda-tope-sin-redis",
            phone="+5491160000123",
            channel="email",
            email=VICTIMA,
            schedule_dispatch=lambda *mail: encolados.append(mail),
        )

    assert exc_info.value.http_status == 503
    assert exc_info.value.error_code == "RATE_LIMIT_UNAVAILABLE"
    assert encolados == []
    guardados = await test_session.scalar(
        select(func.count())
        .select_from(OtpVerification)
        .where(OtpVerification.store_id == "tienda-tope-sin-redis")
    )
    assert guardados == 0


@pytest.mark.asyncio
async def test_el_flujo_normal_no_cambia(
    client: AsyncClient,
    redis_de_estado: _RedisContador,
    cola: Cola,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tienda, _ = await register_and_login(
        client, slug="otp-tope-normal", email="otp-tope-normal@example.com"
    )
    _con_limites(monkeypatch)
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", True)

    status, cuerpo = await _pedir(
        client, tienda, "5491160000777", "normal@example.com", "203.0.113.77"
    )
    assert status == 200, cuerpo
    codigo = cuerpo["data"]["debug_code"]
    assert [(d, codigo in c) for d, _, c in cola.enviados] == [
        ("normal@example.com", True)
    ]

    verificado = await client.post(
        "/public/otp/verify",
        headers={"X-Forwarded-For": "203.0.113.77"},
        json={"store_public_id": tienda, "phone": "+5491160000777", "code": codigo},
    )
    assert verificado.status_code == 200, verificado.text
