"""El apagado de la API cierra el pool de Redis (X-16, 2026-09-19).

Sintoma: `core.redis.close_redis` existia pero nadie la llamaba; el lifespan
de `main.py` no hacia nada despues del `yield`. Al apagar (deploy, reinicio
del contenedor) las conexiones del pool compartido quedaban abiertas del lado
de Redis hasta su timeout, en la misma instancia que sostiene rate limit e
idempotencia de cobros.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

import main


class _Llamadas:
    def __init__(self, falla: bool = False) -> None:
        self.veces = 0
        self._falla = falla

    async def __call__(self) -> None:
        self.veces += 1
        if self._falla:
            raise ConnectionError("redis ya no esta")


async def _rol_ok() -> None:
    return None


def test_el_apagado_cierra_redis(monkeypatch: MonkeyPatch) -> None:
    cierre = _Llamadas()
    monkeypatch.setattr(main, "SETTINGS_BOOT_ERROR", None)
    monkeypatch.setattr(main, "_assert_rls_capable_role", _rol_ok)
    monkeypatch.setattr(main, "close_redis", cierre)

    with TestClient(main.app):
        assert cierre.veces == 0, "no se cierra al arrancar"

    assert cierre.veces == 1


def test_con_boot_error_tambien_se_cierra(monkeypatch: MonkeyPatch) -> None:
    cierre = _Llamadas()
    monkeypatch.setattr(main, "SETTINGS_BOOT_ERROR", "SECRET_KEY placeholder")
    monkeypatch.setattr(main, "close_redis", cierre)

    with TestClient(main.app):
        pass

    assert cierre.veces == 1


def test_un_redis_caido_no_rompe_el_apagado(monkeypatch: MonkeyPatch) -> None:
    """Cierre ordenado, no fragil: si Redis ya no responde, el apagado sigue."""
    cierre = _Llamadas(falla=True)
    monkeypatch.setattr(main, "SETTINGS_BOOT_ERROR", None)
    monkeypatch.setattr(main, "_assert_rls_capable_role", _rol_ok)
    monkeypatch.setattr(main, "close_redis", cierre)

    with TestClient(main.app):
        pass

    assert cierre.veces == 1


@pytest.mark.asyncio
async def test_close_redis_suelta_el_cliente_compartido() -> None:
    import core.redis as redis_mod

    cliente = await redis_mod.get_redis()
    assert redis_mod._redis is cliente

    await redis_mod.close_redis()

    assert redis_mod._redis is None
    assert redis_mod._redis_loop is None
