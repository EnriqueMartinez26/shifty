"""El bypass de RLS se cierra tambien en la conexion, no solo en el ContextVar.

Auditoria B3-13, 2026-09-17. Sintoma: nueve bloques hacian
``set_tenant_context(None, True)`` + ``_apply_tenant_context`` a la entrada y,
en el ``finally``, SOLO ``set_tenant_context(None, False)``. Como
``TenantSession.commit`` reaplica el contexto vigente al momento del commit --
que dentro del bloque sigue siendo el de bypass --, la transaccion que queda
abierta despues del commit conserva ``set_config('app.is_global_admin','true')``
y el ``finally`` no la baja. Hoy no es explotable porque en los nueve casos la
funcion es el ultimo uso de la sesion, pero agregar un ``execute`` despues del
bloque leia todas las tiendas sin que ningun test lo notara: en SQLite
``_apply_tenant_context`` retorna temprano (§2 de CLAUDE.md, RLS).

La guarda nueva es ``tenant_bypass``: un solo lugar que garantiza set+apply a
la entrada y reset+apply a la salida, tambien cuando el cuerpo levanta.
"""

from pathlib import Path
from typing import Any, Generator, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import core.database as database
from core.database import (
    _current_store_id,
    _is_global_admin,
    set_tenant_context,
    tenant_bypass,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]
# Los modulos que hacian el reset a medias. dependencies.py ya lo hacia bien y
# no entra: alli el reset es intermedio y lo sigue un contexto real.
# S-09 (2026-09-18) suma los bloques del portal publico (reserva, "mis
# turnos", lista de espera y la disponibilidad anonima del panel) y los dos
# bloques de payments/router.py (callback OAuth de Mercado Pago y webhook).
# Las tasks de Celery de payments/tasks.py no entran: bypass de tarea entera
# por diseno, con la sesion cerrandose enseguida.
SIN_RESET_A_MEDIAS = (
    "modules/auth/service.py",
    "modules/stores/router.py",
    "modules/public_api/router.py",
    "modules/waitlist/public_router.py",
    "modules/appointments/router.py",
    "modules/payments/router.py",
)


def _sesion_falsa() -> AsyncSession:
    """No toca la base: ``_apply_tenant_context`` esta parcheado."""
    return cast(AsyncSession, object())


@pytest.fixture(autouse=True)
def _contexto_limpio() -> Generator[None, None, None]:
    set_tenant_context(None, False)
    yield
    set_tenant_context(None, False)


@pytest.mark.parametrize("relativo", SIN_RESET_A_MEDIAS)
def test_ningun_bloque_resetea_el_contexto_sin_reaplicarlo(relativo: str) -> None:
    fuente = (BACKEND_ROOT / relativo).read_text(encoding="utf-8")
    assert "set_tenant_context(None, False)" not in fuente, (
        f"{relativo} vuelve a resetear el ContextVar a mano: el bypass se abre "
        "y se cierra con tenant_bypass(db), que ademas lo baja a la conexion."
    )


@pytest.mark.asyncio
async def test_el_bypass_se_aplica_a_la_entrada_y_se_baja_a_la_salida(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aplicados: list[tuple[str | None, bool]] = []

    async def _registrar(session: Any) -> None:
        aplicados.append((_current_store_id.get(), _is_global_admin.get()))

    monkeypatch.setattr(database, "_apply_tenant_context", _registrar)

    async with tenant_bypass(_sesion_falsa()):
        assert _is_global_admin.get() is True

    assert aplicados == [(None, True), (None, False)], (
        "el bypass no se bajo a la conexion al salir del bloque"
    )
    assert _is_global_admin.get() is False


class _SesionQueRegistraRollback:
    """Sesion falsa: registra el rollback con el contexto vigente."""

    def __init__(self, *, falla: bool = False) -> None:
        self.rollbacks: list[tuple[str | None, bool]] = []
        self.falla = falla

    async def rollback(self) -> None:
        self.rollbacks.append((_current_store_id.get(), _is_global_admin.get()))
        if self.falla:
            raise RuntimeError("la conexion tambien murio")


@pytest.mark.asyncio
async def test_si_el_cuerpo_levanta_se_resetea_y_se_hace_rollback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Con excepcion no se reaplica a la salida (``connection()`` podria
    levantar y tapar el error original): se resetea el ContextVar y el
    rollback termina la transaccion que tenia el bypass."""
    aplicados: list[tuple[str | None, bool]] = []

    async def _registrar(session: Any) -> None:
        aplicados.append((_current_store_id.get(), _is_global_admin.get()))

    monkeypatch.setattr(database, "_apply_tenant_context", _registrar)
    sesion = _SesionQueRegistraRollback()

    with pytest.raises(RuntimeError, match="fallo del flujo"):
        async with tenant_bypass(cast(AsyncSession, sesion)):
            raise RuntimeError("fallo del flujo")

    assert aplicados == [(None, True)]
    assert sesion.rollbacks == [(None, False)], (
        "el rollback tiene que correr con el contexto ya reseteado"
    )
    assert _is_global_admin.get() is False


@pytest.mark.asyncio
async def test_un_rollback_fallido_no_tapa_el_error_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _noop(session: Any) -> None:
        return None

    monkeypatch.setattr(database, "_apply_tenant_context", _noop)
    sesion = _SesionQueRegistraRollback(falla=True)

    with pytest.raises(LookupError, match="original"):
        async with tenant_bypass(cast(AsyncSession, sesion)):
            raise LookupError("original")

    assert sesion.rollbacks == [(None, False)]
    assert _is_global_admin.get() is False
