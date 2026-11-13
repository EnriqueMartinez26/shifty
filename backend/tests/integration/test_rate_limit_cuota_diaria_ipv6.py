"""El cupo diario de reservas por IP y tienda agrupa IPv6 por su /64 (#277).

2026-11-02. Sintoma: el cupo (10 reservas exitosas por IP, tienda y dia)
contaba la direccion IPv6 exacta, y un cliente con un /64 rotaba direcciones
para reservar sin tope. Ahora las direcciones del mismo /64 comparten cupo;
otro /64 y las IPv4 siguen con el suyo. Va por la API publica, como
``test_portal_cuota_diaria_por_ip.py``.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

import modules.public_api.service as public_service
from tests.integration.test_caracterizacion_alta_publica import _tienda
from tests.integration.test_portal_cuota_diaria_por_ip import (
    _con_limites,
    _cuerpo,
    _RedisDeEstado,
    _reservar,
    redis_de_estado,  # noqa: F401 - fixture
)


@pytest.mark.asyncio
async def test_el_mismo_64_comparte_el_cupo_diario(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    redis_de_estado: _RedisDeEstado,  # noqa: F811
) -> None:
    t = await _tienda(client, "cuota-ipv6")
    _con_limites(monkeypatch)
    monkeypatch.setattr(public_service, "PUBLIC_BOOKINGS_PER_IP_PER_STORE_PER_DAY", 2)

    for i, ip in enumerate(("2001:db8:1:2::a", "2001:db8:1:2::b")):
        res = await _reservar(client, _cuerpo(t, i, ip), ip)
        assert res.status_code == 201, (ip, res.text)

    rotada = "2001:db8:1:2:ffff::c"
    tercera = await _reservar(client, _cuerpo(t, 2, rotada), rotada)
    assert tercera.status_code == 429, tercera.text
    assert tercera.json()["error_code"] == "BOOKING_DAILY_LIMIT"
    assert list(redis_de_estado.de_la_cuota().values()) == [2]

    # Otro /64 y una IPv4 (tambien mapeada) tienen su propio cupo.
    for i, ip in enumerate(("2001:db8:1:3::a", "203.0.113.7", "::ffff:203.0.113.8")):
        res = await _reservar(client, _cuerpo(t, 3 + i, ip), ip)
        assert res.status_code == 201, (ip, res.text)


@pytest.mark.asyncio
async def test_una_ipv4_mapeada_comparte_el_cupo_de_su_ipv4(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    redis_de_estado: _RedisDeEstado,  # noqa: F811
) -> None:
    t = await _tienda(client, "cuota-ipv4-mapeada")
    _con_limites(monkeypatch)
    monkeypatch.setattr(public_service, "PUBLIC_BOOKINGS_PER_IP_PER_STORE_PER_DAY", 1)

    nativa = await _reservar(client, _cuerpo(t, 0, "203.0.113.7"), "203.0.113.7")
    assert nativa.status_code == 201, nativa.text
    mapeada = "::ffff:203.0.113.7"
    segunda = await _reservar(client, _cuerpo(t, 1, mapeada), mapeada)
    assert segunda.status_code == 429, segunda.text
    assert list(redis_de_estado.de_la_cuota().values()) == [1]
