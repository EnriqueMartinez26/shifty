"""Un pedido de OTP que no entrega mail no invalida el codigo vivo.

2026-10-05, sintoma (confirmado por Enrique sobre #121): ``request_code``
guardaba el codigo nuevo -y con eso consumia el anterior- ANTES de encolar
el mail. Si el encolado fallaba (``core.enqueue.enqueue`` devuelve False con
el broker caido o lento), el titular se quedaba sin codigo valido: el de su
casilla ya no verificaba y el nuevo nunca le llegaba. Pidiendo codigos para
un telefono ajeno con el broker degradado se trababa la verificacion de esa
persona (reserva y "Mis turnos") sin mandarle nada. El tope por buzon de
destino tenia el mismo efecto hasta el arreglo de #121 (de2557c7); estos
tests fijan los dos caminos.

Regla: el codigo vivo solo se reemplaza cuando el mail del codigo nuevo
quedo en la cola (tope permitido Y ``enqueue`` en True). La respuesta HTTP
no cambia de status ni de forma en ningun caso (regla 20, AUD2-B4-05).
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import core.rate_limit as rate_limit
import modules.notifications.tasks as tasks
import modules.otp.service as otp_service
from core.config import settings
from modules.otp.model import OtpVerification
from modules.stores.model import Store
from tests.integration.test_feature_flags_finance_and_public_privacy import (
    register_and_login,
)
from tests.integration.test_otp_oraculo_por_entrega import (
    EMAIL_CLIENTE,
    TELEFONO_CLIENTE,
    _tienda_con_cliente,
)
from tests.integration.test_otp_por_email import Cola
from tests.integration.test_otp_tope_por_mail_destino import _RedisContador

TELEFONO = "5491160001234"
EMAIL = "titular@example.com"
EMAIL_TIPEADO = "tipeado@example.com"
_CODIGO = re.compile(r"\b\d{6}\b")


class _BrokerCaido:
    """``send_otp_email`` con el broker inalcanzable: ``enqueue`` da False."""

    name = "send_otp_email"

    def __init__(self) -> None:
        self.intentos = 0

    def delay(self, *_args: object) -> None:
        self.intentos += 1
        raise ConnectionError("broker down")


@pytest.fixture
def cola(monkeypatch: pytest.MonkeyPatch) -> Cola:
    encolados = Cola()
    monkeypatch.setattr(tasks, "send_otp_email", encolados)
    return encolados


def _topear(
    monkeypatch: pytest.MonkeyPatch, *, topeados: set[str]
) -> Callable[[str], Awaitable[bool]]:
    """Tope por buzon: los de ``topeados`` ya agotaron su cuota."""

    async def permite(destino: str) -> bool:
        return destino not in topeados

    monkeypatch.setattr(otp_service, "_destination_allows_mail", permite)
    return permite


async def _pedir(
    client: AsyncClient, tienda: str, telefono: str, email: str
) -> dict[str, Any]:
    respuesta = await client.post(
        "/public/otp/request",
        json={
            "store_public_id": tienda,
            "phone": f"+{telefono}",
            "channel": "email",
            "email": email,
        },
    )
    assert respuesta.status_code == 200, respuesta.text
    cuerpo: dict[str, Any] = respuesta.json()
    return cuerpo


async def _verifica(
    client: AsyncClient, tienda: str, telefono: str, codigo: str
) -> bool:
    respuesta = await client.post(
        "/public/otp/verify",
        json={"store_public_id": tienda, "phone": f"+{telefono}", "code": codigo},
    )
    assert respuesta.status_code in {200, 400}, respuesta.text
    return respuesta.status_code == 200


def _ultimo_codigo(cola: Cola, destino: str) -> str:
    cuerpos = [cuerpo for to, _, cuerpo in cola.enviados if to == destino]
    assert cuerpos, f"no se encolo nada para {destino}"
    encontrado = _CODIGO.search(cuerpos[-1])
    assert encontrado is not None, "el ultimo mail a ese buzon no trae codigo"
    return encontrado.group(0)


async def _filas(session: AsyncSession, tienda: str, telefono: str) -> int:
    store_id = await session.scalar(select(Store.id).where(Store.public_id == tienda))
    cantidad = await session.scalar(
        select(func.count())
        .select_from(OtpVerification)
        .where(
            OtpVerification.store_id == store_id,
            OtpVerification.phone == f"+{telefono}",
        )
    )
    return int(cantidad or 0)


@pytest.mark.asyncio
async def test_tope_del_destino_conserva_el_codigo_vivo(
    client: AsyncClient,
    test_session: AsyncSession,
    cola: Cola,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2026-10-05: el tope corta el mail; el codigo A de la casilla sigue."""
    tienda, _ = await register_and_login(
        client, slug="otp-no-pisa-tope", email="otp-no-pisa-tope@example.com"
    )
    await _pedir(client, tienda, TELEFONO, EMAIL)
    codigo_a = _ultimo_codigo(cola, EMAIL)
    filas = await _filas(test_session, tienda, TELEFONO)

    _topear(monkeypatch, topeados={EMAIL})
    await _pedir(client, tienda, TELEFONO, EMAIL)

    assert len(cola.enviados) == 1, "el pedido topeado encolo un mail"
    assert await _filas(test_session, tienda, TELEFONO) == filas, (
        "el pedido topeado guardo un codigo nuevo"
    )
    assert await _verifica(client, tienda, TELEFONO, codigo_a)


@pytest.mark.asyncio
async def test_encolado_fallido_conserva_el_codigo_vivo(
    client: AsyncClient,
    test_session: AsyncSession,
    cola: Cola,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2026-10-05: con el broker caido, pedir otro codigo mataba el de la
    casilla sin mandar reemplazo. Ahora no se guarda nada y A sigue."""
    tienda, _ = await register_and_login(
        client, slug="otp-no-pisa-broker", email="otp-no-pisa-broker@example.com"
    )
    await _pedir(client, tienda, TELEFONO, EMAIL)
    codigo_a = _ultimo_codigo(cola, EMAIL)
    filas = await _filas(test_session, tienda, TELEFONO)

    broker = _BrokerCaido()
    monkeypatch.setattr(tasks, "send_otp_email", broker)
    cuerpos = [await _pedir(client, tienda, TELEFONO, EMAIL) for _ in range(3)]

    assert broker.intentos == 3
    assert await _verifica(client, tienda, TELEFONO, codigo_a), (
        "un encolado fallido invalido el codigo que el titular ya tenia"
    )
    assert await _filas(test_session, tienda, TELEFONO) == filas
    for cuerpo in cuerpos:
        assert cuerpo["ok"] is True
        assert "debug_code" not in cuerpo, "se expuso un codigo que nadie recibe"


@pytest.mark.asyncio
async def test_con_el_mail_encolado_el_codigo_nuevo_reemplaza_al_viejo(
    client: AsyncClient, cola: Cola
) -> None:
    """Flujo normal sin cambios: B reemplaza a A, B verifica y A no."""
    tienda, _ = await register_and_login(
        client, slug="otp-no-pisa-normal", email="otp-no-pisa-normal@example.com"
    )
    await _pedir(client, tienda, TELEFONO, EMAIL)
    codigo_a = _ultimo_codigo(cola, EMAIL)
    cuerpo = await _pedir(client, tienda, TELEFONO, EMAIL)
    codigo_b = _ultimo_codigo(cola, EMAIL)
    if codigo_b == codigo_a:  # 1 en 10^6: el mismo numero no prueba nada
        cuerpo = await _pedir(client, tienda, TELEFONO, EMAIL)
        codigo_b = _ultimo_codigo(cola, EMAIL)

    assert cuerpo["debug_code"] == codigo_b
    assert not await _verifica(client, tienda, TELEFONO, codigo_a)
    assert await _verifica(client, tienda, TELEFONO, codigo_b)


@pytest.mark.asyncio
async def test_el_tope_del_aviso_no_frena_el_codigo(
    client: AsyncClient,
    test_session: AsyncSession,
    cola: Cola,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El telefono es de un cliente: el codigo va a la ficha y el aviso sin
    codigo (AUD2-B4-05) al tipeado. Topear el aviso no corta el codigo: B
    sale a la ficha, reemplaza a A y verifica."""
    tienda = await _tienda_con_cliente(client, test_session, "otp-no-pisa-aviso")
    await _pedir(client, tienda, TELEFONO_CLIENTE, EMAIL_CLIENTE)
    codigo_a = _ultimo_codigo(cola, EMAIL_CLIENTE)

    _topear(monkeypatch, topeados={EMAIL_TIPEADO})
    await _pedir(client, tienda, TELEFONO_CLIENTE, EMAIL_TIPEADO)

    destinos = [to for to, _, _ in cola.enviados]
    assert destinos == [EMAIL_CLIENTE, EMAIL_CLIENTE], "el aviso topeado salio"
    codigo_b = _ultimo_codigo(cola, EMAIL_CLIENTE)
    if codigo_b != codigo_a:  # 1 en 10^6 de que coincidan
        assert not await _verifica(client, tienda, TELEFONO_CLIENTE, codigo_a)
    assert await _verifica(client, tienda, TELEFONO_CLIENTE, codigo_b)


@pytest.mark.asyncio
async def test_el_codigo_a_la_ficha_que_no_se_encola_conserva_el_vivo(
    client: AsyncClient,
    test_session: AsyncSession,
    cola: Cola,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con aviso al tipeado, lo que decide es el mail del CODIGO: si no se
    encola, A (en la casilla de la ficha) sigue valido."""
    tienda = await _tienda_con_cliente(client, test_session, "otp-no-pisa-ficha")
    await _pedir(client, tienda, TELEFONO_CLIENTE, EMAIL_CLIENTE)
    codigo_a = _ultimo_codigo(cola, EMAIL_CLIENTE)
    filas = await _filas(test_session, tienda, TELEFONO_CLIENTE)

    async def encola_solo_el_aviso(task: Any, to: str, *args: Any, **_: Any) -> bool:
        if to == EMAIL_CLIENTE:
            return False
        task.delay(to, *args)
        return True

    monkeypatch.setattr(tasks, "enqueue", encola_solo_el_aviso)
    await _pedir(client, tienda, TELEFONO_CLIENTE, EMAIL_TIPEADO)

    assert await _filas(test_session, tienda, TELEFONO_CLIENTE) == filas
    assert await _verifica(client, tienda, TELEFONO_CLIENTE, codigo_a)


@pytest.mark.asyncio
async def test_la_respuesta_es_la_misma_en_todos_los_caminos(
    client: AsyncClient,
    cola: Cola,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Produccion (sin debug_code): normal, topeado y broker caido responden
    el mismo status y la misma forma de sobre."""
    tienda, _ = await register_and_login(
        client, slug="otp-no-pisa-forma", email="otp-no-pisa-forma@example.com"
    )
    monkeypatch.setattr(settings, "OTP_DEBUG_EXPOSE_CODE", False)

    async def pedir() -> tuple[int, object]:
        respuesta = await client.post(
            "/public/otp/request",
            headers={"x-raw-response": "false"},
            json={
                "store_public_id": tienda,
                "phone": f"+{TELEFONO}",
                "channel": "email",
                "email": EMAIL,
            },
        )
        cuerpo = respuesta.json()
        data = cuerpo.get("data", {})
        return respuesta.status_code, (sorted(cuerpo), sorted(data))

    normal = await pedir()
    with monkeypatch.context() as caido:
        caido.setattr(tasks, "send_otp_email", _BrokerCaido())
        sin_broker = await pedir()
    with monkeypatch.context() as tope:
        _topear(tope, topeados={EMAIL})
        topeado = await pedir()

    assert normal[0] == 200
    assert normal == sin_broker == topeado


@pytest.mark.asyncio
async def test_los_contadores_cuentan_igual_aunque_el_mail_no_salga(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """El presupuesto por telefono y la cuota del buzon se consumen una vez
    por pedido, salga el mail o no: el arreglo no cambia los limites."""
    tienda, _ = await register_and_login(
        client, slug="otp-no-pisa-cuotas", email="otp-no-pisa-cuotas@example.com"
    )
    redis = _RedisContador()

    async def fake_get_redis() -> _RedisContador:
        return redis

    monkeypatch.setattr(rate_limit, "get_redis", fake_get_redis)
    monkeypatch.setattr(otp_service, "get_redis", fake_get_redis)
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(tasks, "send_otp_email", _BrokerCaido())

    for _ in range(2):
        await _pedir(client, tienda, TELEFONO, EMAIL)

    por_telefono = [v for k, v in redis.valores.items() if k.startswith("otp:req:")]
    por_buzon = [v for k, v in redis.valores.items() if "otp:mail-destination" in k]
    assert por_telefono == [2]
    assert sorted(por_buzon) == [2, 2]  # ventana de hora y de dia
