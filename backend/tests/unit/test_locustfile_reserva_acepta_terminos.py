"""El payload de reserva del locustfile manual acepta los terminos (X-19).

2026-09-30. Sintoma: ``POST /public/appointments`` exige ``accepts_terms: true``
desde PV-09 (``PublicBookingCreate.require_terms``) y ``loadtests/locustfile.py``
no lo mandaba: toda reserva de la carga daba 422 y la prueba medía el rechazo.
Se lee el archivo como texto (AST): importar ``locust`` parchea el proceso con
gevent. Los campos del payload tienen que existir en el schema real.
"""

from __future__ import annotations

import ast
from pathlib import Path

from modules.public_api.schemas import PublicBookingCreate

LOCUSTFILE = Path(__file__).resolve().parents[2] / "loadtests" / "locustfile.py"


def _reservas() -> list[dict[str, ast.expr]]:
    tree = ast.parse(LOCUSTFILE.read_text(encoding="utf-8"))
    dicts: list[dict[str, ast.expr]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        claves = {
            key.value: value
            for key, value in zip(node.keys, node.values, strict=True)
            if isinstance(key, ast.Constant) and isinstance(key.value, str)
        }
        if "starts_at" in claves and "service_id" in claves:
            dicts.append(claves)
    return dicts


def test_la_reserva_del_locustfile_manda_accepts_terms_true() -> None:
    reservas = _reservas()
    assert reservas, "no se encontro el payload de reserva del locustfile"
    for claves in reservas:
        valor = claves.get("accepts_terms")
        assert isinstance(valor, ast.Constant) and valor.value is True


def test_los_campos_de_la_reserva_existen_en_el_schema() -> None:
    campos = set(PublicBookingCreate.model_fields)
    for claves in _reservas():
        assert set(claves) <= campos, sorted(set(claves) - campos)
