"""Regla 21 de CLAUDE.md: la API tolera el respaldo de settings SOLO para
responder 503 con detalle.

2026-09-16 (audit B7-01): con ``SETTINGS_BOOT_ERROR`` seteado el lifespan
corria ``_assert_rls_capable_role`` contra la ``DATABASE_URL`` de respaldo
(``localhost/invalid``), el startup de uvicorn fallaba y el proceso moria en
crash-loop: el 503 ``BACKEND_BOOT_FAILED`` de ``BootErrorMiddleware`` nunca
llegaba a servirse (nginx devolvia 502 sin detalle).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

import main


class _FakeConnection:
    """Conexion Postgres simulada: devuelve la fila de pg_roles que le den."""

    def __init__(self, row: tuple[bool, bool] | None) -> None:
        self.dialect = SimpleNamespace(name="postgresql")
        self._row = row

    async def __aenter__(self) -> "_FakeConnection":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    async def execute(self, *_: Any) -> Any:
        return SimpleNamespace(one_or_none=lambda: self._row)


class _FakeEngine:
    def __init__(self, row: tuple[bool, bool] | None) -> None:
        self._row = row

    def connect(self) -> _FakeConnection:
        return _FakeConnection(self._row)


class _UnreachableEngine:
    """La DATABASE_URL de respaldo apunta a una base que no existe."""

    def connect(self) -> Any:
        raise OSError("connect() failed: localhost/invalid")


def test_con_boot_error_la_app_arranca_y_responde_503_en_toda_ruta(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(main, "SETTINGS_BOOT_ERROR", "SECRET_KEY parece un placeholder")
    monkeypatch.setattr(main, "engine", _UnreachableEngine())

    # TestClient como context manager ejecuta el lifespan (startup/shutdown).
    with TestClient(main.app) as client:
        for path in ("/", "/auth/login", "/ops/health", "/no-existe"):
            response = client.get(path)
            assert response.status_code == 503, path
            body = response.json()
            assert body["success"] is False
            assert body["error_code"] == "BACKEND_BOOT_FAILED"
            assert body["detail"] == "SECRET_KEY parece un placeholder"


def test_sin_boot_error_el_arranque_sigue_abortando_si_el_rol_saltea_rls(
    monkeypatch: MonkeyPatch,
) -> None:
    """Guarda de §2: main.py aborta si el rol puede saltar RLS. Sigue viva."""
    monkeypatch.setattr(main, "SETTINGS_BOOT_ERROR", None)
    monkeypatch.setattr(main, "engine", _FakeEngine((False, True)))

    with pytest.raises(RuntimeError, match="BYPASSRLS"):
        with TestClient(main.app):
            pass


def test_sin_boot_error_una_base_inalcanzable_sigue_matando_el_proceso(
    monkeypatch: MonkeyPatch,
) -> None:
    """Con config valida no se tolera una base caida: el proceso muere."""
    monkeypatch.setattr(main, "SETTINGS_BOOT_ERROR", None)
    monkeypatch.setattr(main, "engine", _UnreachableEngine())

    with pytest.raises(OSError, match="localhost/invalid"):
        with TestClient(main.app):
            pass
