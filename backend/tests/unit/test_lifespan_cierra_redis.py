"""El apagado de la API cierra el pool de Redis y el de Postgres.

Sintoma (X-16, 2026-09-19): `core.redis.close_redis` existia pero nadie la
llamaba; el lifespan de `main.py` no hacia nada despues del `yield`. Al apagar
(deploy, reinicio del contenedor) las conexiones del pool compartido quedaban
abiertas del lado de Redis hasta su timeout, en la misma instancia que sostiene
rate limit e idempotencia de cobros.

X-16 cerro la mitad del problema (AUD2-B7-05, 2026-09-20): el pool de
SQLAlchemy tenia el mismo modo de fallo y no habia UN SOLO `engine.dispose()`
en todo el backend. Por proceso de uvicorn quedaban hasta
`DB_POOL_SIZE + DB_MAX_OVERFLOW` (10 + 5) conexiones abiertas contra Postgres
tras cada apagado, hasta que las cerrara el timeout del servidor. Con
`restart: always` y un contenedor de Postgres de 256M, un deploy con reinicios
seguidos puede dejar la base sin cupo para el proceso nuevo: el mismo recurso
que ya se agoto una vez (CLAUDE.md regla 5, 2026-09-04).
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


class _Engine:
    """Doble del engine global: solo interesa si se lo desecha."""

    def __init__(self, falla: bool = False) -> None:
        self.veces = 0
        self._falla = falla

    async def dispose(self) -> None:
        self.veces += 1
        if self._falla:
            raise OSError("la base ya no responde")


def _lifespan_con_engine(monkeypatch: MonkeyPatch, motor: _Engine) -> None:
    monkeypatch.setattr(main, "engine", motor)


def test_el_apagado_desecha_el_pool_de_postgres(monkeypatch: MonkeyPatch) -> None:
    motor = _Engine()
    monkeypatch.setattr(main, "SETTINGS_BOOT_ERROR", None)
    monkeypatch.setattr(main, "_assert_rls_capable_role", _rol_ok)
    monkeypatch.setattr(main, "close_redis", _Llamadas())
    _lifespan_con_engine(monkeypatch, motor)

    with TestClient(main.app):
        assert motor.veces == 0, "no se desecha al arrancar"

    assert motor.veces == 1


def test_con_boot_error_el_pool_tambien_se_desecha(monkeypatch: MonkeyPatch) -> None:
    motor = _Engine()
    monkeypatch.setattr(main, "SETTINGS_BOOT_ERROR", "SECRET_KEY placeholder")
    monkeypatch.setattr(main, "close_redis", _Llamadas())
    _lifespan_con_engine(monkeypatch, motor)

    with TestClient(main.app):
        pass

    assert motor.veces == 1


def test_una_base_caida_no_rompe_el_apagado(monkeypatch: MonkeyPatch) -> None:
    """Cierre ordenado, no fragil: igual que con Redis, se registra y se sigue."""
    motor = _Engine(falla=True)
    cierre = _Llamadas()
    monkeypatch.setattr(main, "SETTINGS_BOOT_ERROR", None)
    monkeypatch.setattr(main, "_assert_rls_capable_role", _rol_ok)
    monkeypatch.setattr(main, "close_redis", cierre)
    _lifespan_con_engine(monkeypatch, motor)

    with TestClient(main.app):
        pass

    assert motor.veces == 1
    # Redis se cierra aunque la base falle: un cierre no puede tapar al otro.
    assert cierre.veces == 1


def test_un_redis_caido_no_impide_desechar_el_pool(monkeypatch: MonkeyPatch) -> None:
    motor = _Engine()
    monkeypatch.setattr(main, "SETTINGS_BOOT_ERROR", None)
    monkeypatch.setattr(main, "_assert_rls_capable_role", _rol_ok)
    monkeypatch.setattr(main, "close_redis", _Llamadas(falla=True))
    _lifespan_con_engine(monkeypatch, motor)

    with TestClient(main.app):
        pass

    assert motor.veces == 1


@pytest.mark.asyncio
async def test_close_redis_suelta_el_cliente_compartido() -> None:
    import core.redis as redis_mod

    cliente = await redis_mod.get_redis()
    assert redis_mod._redis is cliente

    await redis_mod.close_redis()

    assert redis_mod._redis is None
    assert redis_mod._redis_loop is None
