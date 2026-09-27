"""``staff_services`` se declara una sola vez: en su modelo ORM.

Auditoria B3-20, 2026-09-18. Sintoma: ``modules/staff/model.py`` redeclaraba la
tabla ``staff_services`` con ``Table(..., extend_existing=True)`` sobre la MISMA
``MetaData`` que ``StaffServiceModel`` y sin la columna ``rating``. Funcionaba
solo porque el modelo ORM se importaba unas lineas antes: ``extend_existing``
fusionaba la redeclaracion con la tabla ya registrada y escondia la
competencia. Invertir esos dos imports dejaba una tabla sin ``rating``. Ademas
``modules.staff.model`` no esta en ``MODEL_MODULES``, asi que
``test_model_registry`` no lo audita.

El nombre ``staff_services`` se conserva como alias de
``StaffServiceModel.__table__``: su unico consumidor
(``scripts/seed_simulation.py``) sigue funcionando sin cambios.
"""

import ast
from pathlib import Path

from infrastructure.persistence.models.staff_service import StaffServiceModel
from modules.staff.model import staff_services

MODELO = Path(__file__).resolve().parents[2] / "modules" / "staff" / "model.py"


def test_el_modulo_de_staff_no_redeclara_tablas() -> None:
    arbol = ast.parse(MODELO.read_text(encoding="utf-8"))
    declaraciones = [
        nodo.lineno
        for nodo in ast.walk(arbol)
        if isinstance(nodo, ast.Call)
        and (
            (isinstance(nodo.func, ast.Name) and nodo.func.id == "Table")
            or (isinstance(nodo.func, ast.Attribute) and nodo.func.attr == "Table")
        )
    ]
    assert not declaraciones, (
        f"modules/staff/model.py declara una Table en las lineas {declaraciones}: "
        "staff_services ya es StaffServiceModel.__table__."
    )


def test_staff_services_es_la_tabla_del_modelo_orm() -> None:
    assert staff_services is StaffServiceModel.__table__
    assert {c.name for c in staff_services.c} == {"staff_id", "service_id", "rating"}
