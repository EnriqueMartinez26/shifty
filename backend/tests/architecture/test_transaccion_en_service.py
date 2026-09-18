"""El dueno de la transaccion de ``ledger`` y ``promotions`` es su service.

2026-09-17, hallazgo B2-09: los cinco ``await db.commit()`` de
``modules/ledger/router.py`` (2) y ``modules/promotions/router.py`` (3) vivian
en los handlers HTTP, junto con la logica de negocio: el saldo incremental con
su advisory lock, el chequeo de codigos duplicados y la ventana de vigencia.

CLAUDE.md §2 declara la deuda acotada a ``public_api/router.py``,
``payments/router.py``, ``stores/router.py`` y ``superadmin/repository.py``:
ledger y promotions la habian extendido a dos modulos mas. El costo concreto
era que el lock que serializa ``balance_after`` quedaba en la capa equivocada y
no se podia ejercer sin levantar HTTP.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]

# Modulos que ya migraron al patron de `appointments`: el router no commitea.
MODULOS_MIGRADOS = ("ledger", "promotions")


def _llamadas_a_commit(path: Path) -> list[int]:
    """Lineas donde el archivo llama a ``.commit()`` sobre lo que sea."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "commit"
    ]


def test_los_routers_migrados_no_commitean() -> None:
    for modulo in MODULOS_MIGRADOS:
        router = BACKEND_ROOT / "modules" / modulo / "router.py"
        lineas = _llamadas_a_commit(router)
        assert not lineas, (
            f"{router} commitea en las lineas {lineas}: la transaccion es del "
            "service (CLAUDE.md §2). No se agrega un commit nuevo en un router."
        )


def test_los_services_migrados_son_los_duenos_de_la_transaccion() -> None:
    # La contracara del test anterior: el commit no desaparecio, se mudo. Sin
    # esto, borrar el commit y dejar el endpoint sin persistir tambien pasaria.
    for modulo in MODULOS_MIGRADOS:
        service = BACKEND_ROOT / "modules" / modulo / "service.py"
        assert service.exists(), f"{modulo} no tiene capa de servicio"
        assert _llamadas_a_commit(service), (
            f"{service} no commitea: el modulo quedo sin dueno de la transaccion."
        )
