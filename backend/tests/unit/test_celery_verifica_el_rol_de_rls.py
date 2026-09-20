"""El worker y beat tambien abortan si el rol puede saltar RLS.

AUD2-B7-08 (2026-09-20). `_assert_rls_capable_role` corria SOLO en el lifespan
de FastAPI. El worker y beat se conectan con la MISMA `DATABASE_URL` (viven en
el mismo bloque `x-app-environment` del compose, junto a
`MIGRATION_DATABASE_URL`: confundirlas es un typo de una palabra). Si alguien
apuntaba `DATABASE_URL` al rol dueno `shifty_user`, la API moria ruidosamente y
Celery seguia trabajando con el aislamiento multi-tenant desactivado, en
silencio, sobre los turnos, los pagos y el outbox de TODAS las tiendas.

CLAUDE.md §2 presenta este chequeo como LA garantia de que RLS aplica; que viva
en un solo proceso de los tres la deja a medias. Es la misma clase de fallo que
la regla 21 ya obliga a matar en `worker_init`/`beat_init`.
"""

from __future__ import annotations

import pytest
from pytest import MonkeyPatch

import core.celery_app as celery_app
from tests.unit.test_boot_error_lifespan import _FakeEngine, _UnreachableEngine


def test_el_arranque_de_celery_aborta_si_el_rol_saltea_rls(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(celery_app, "SETTINGS_BOOT_ERROR", None)
    monkeypatch.setattr(celery_app, "engine", _FakeEngine((False, True)))

    with pytest.raises(SystemExit, match="BYPASSRLS"):
        celery_app._start_worker_process()


def test_el_arranque_de_celery_aborta_si_el_rol_es_superusuario(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(celery_app, "SETTINGS_BOOT_ERROR", None)
    monkeypatch.setattr(celery_app, "engine", _FakeEngine((True, False)))

    with pytest.raises(SystemExit, match="superusuario"):
        celery_app._start_worker_process()


def test_el_arranque_de_celery_aborta_si_la_base_no_responde(
    monkeypatch: MonkeyPatch,
) -> None:
    """Un worker que no puede verificar el rol no puede declararse listo.

    El despachador de signals de Celery se traga cualquier `Exception`, asi que
    un `OSError` dejaria al worker "ready" sin haber verificado nada. Por eso se
    traduce a `SystemExit`, que no es `Exception`.
    """
    monkeypatch.setattr(celery_app, "SETTINGS_BOOT_ERROR", None)
    monkeypatch.setattr(celery_app, "engine", _UnreachableEngine())

    with pytest.raises(SystemExit, match="localhost/invalid"):
        celery_app._start_worker_process()


def test_un_rol_restringido_deja_arrancar(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(celery_app, "SETTINGS_BOOT_ERROR", None)
    monkeypatch.setattr(celery_app, "engine", _FakeEngine((False, False)))

    celery_app._start_worker_process()


def test_con_settings_de_respaldo_ni_se_consulta_la_base(
    monkeypatch: MonkeyPatch,
) -> None:
    """Regla 21 primero: con config invalida se muere antes de tocar la base.

    Es el mismo corte que hace el lifespan de la API: la DATABASE_URL de
    respaldo apunta a localhost/invalid y consultarla solo cambia el mensaje
    por uno peor.
    """
    monkeypatch.setattr(celery_app, "SETTINGS_BOOT_ERROR", "SECRET_KEY placeholder")
    monkeypatch.setattr(celery_app, "engine", _UnreachableEngine())

    with pytest.raises(SystemExit, match="SECRET_KEY placeholder"):
        celery_app._start_worker_process()


def test_el_chequeo_no_deja_conexiones_en_el_pool_del_padre(
    monkeypatch: MonkeyPatch,
) -> None:
    """AUD2-B7-08 (2026-09-20): el chequeo envenenaba el pool de los hijos.

    `worker_init` corre en el proceso PADRE de prefork (`WorkController.
    setup_instance`), ANTES del fork. `assert_rls_capable_role` abre una
    conexion con `bind.connect()` y al salir del `async with` esa conexion
    vuelve al QueuePool del engine global. Cada hijo forkeado hereda ese
    registro -mismo descriptor, atado al event loop del padre-, asi que la
    primera tarea que la saque del pool muere con "attached to a different
    loop" / "Event loop is closed": exactamente el bug que documenta
    `core/worker_loop.py` y que ese modulo existe para evitar. `pool_pre_ping`
    no salva, porque el ping tambien corre sobre la conexion prestada.

    Por eso el padre desecha el pool apenas termina de verificar.
    """
    motor = _FakeEngine((False, False))
    monkeypatch.setattr(celery_app, "SETTINGS_BOOT_ERROR", None)
    monkeypatch.setattr(celery_app, "engine", motor)

    celery_app._start_worker_process()

    assert motor.dispose_count == 1


def test_el_pool_se_desecha_tambien_cuando_el_rol_esta_mal(
    monkeypatch: MonkeyPatch,
) -> None:
    """El proceso muere igual, pero no deja el pool sucio para nadie."""
    motor = _FakeEngine((False, True))
    monkeypatch.setattr(celery_app, "SETTINGS_BOOT_ERROR", None)
    monkeypatch.setattr(celery_app, "engine", motor)

    with pytest.raises(SystemExit, match="BYPASSRLS"):
        celery_app._start_worker_process()

    assert motor.dispose_count == 1


def test_un_dispose_que_falla_no_tapa_el_motivo_real(
    monkeypatch: MonkeyPatch,
) -> None:
    """El mensaje del abort es el del rol, no el del cierre del pool.

    Si el `finally` levantara, el operador leeria un error de pool y no "el rol
    puede saltar RLS", que es lo unico accionable.
    """

    class _MotorConDisposeRoto(_FakeEngine):
        async def dispose(self) -> None:
            raise OSError("no se pudo cerrar el pool")

    monkeypatch.setattr(celery_app, "SETTINGS_BOOT_ERROR", None)
    monkeypatch.setattr(celery_app, "engine", _MotorConDisposeRoto((True, False)))

    with pytest.raises(SystemExit, match="superusuario"):
        celery_app._start_worker_process()


def test_con_settings_de_respaldo_ni_se_desecha_nada(
    monkeypatch: MonkeyPatch,
) -> None:
    """Regla 21 primero: si no se abrio el pool, no hay nada que cerrar."""
    motor = _UnreachableEngine()
    monkeypatch.setattr(celery_app, "SETTINGS_BOOT_ERROR", "SECRET_KEY placeholder")
    monkeypatch.setattr(celery_app, "engine", motor)

    with pytest.raises(SystemExit, match="SECRET_KEY placeholder"):
        celery_app._start_worker_process()

    assert motor.dispose_count == 0
