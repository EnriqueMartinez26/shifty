"""``first_overlapping_day``: la validacion de la semana antes de guardarla.

2026-10-08 (``PUT /staff/{id}/schedules``). Misma regla que
``StaffRepository._assert_no_overlap``: se pisan si una empieza antes de que
termine la otra; tocarse en el borde es valido.
"""

from __future__ import annotations

from datetime import time
from typing import Any

import pytest

from modules.staff.service import first_overlapping_day


def _f(dia: int, inicio: int, fin: int) -> dict[str, Any]:
    return {"day_of_week": dia, "start_time": time(inicio), "end_time": time(fin)}


@pytest.mark.parametrize(
    ("franjas", "esperado"),
    [
        ([], None),
        ([_f(0, 9, 18)], None),
        ([_f(0, 9, 13), _f(0, 13, 17)], None),
        ([_f(0, 9, 13), _f(1, 10, 12)], None),
        ([_f(2, 9, 13), _f(2, 12, 15)], 2),
        # Una franja larga que contiene a otra, cargadas en cualquier orden.
        ([_f(3, 10, 11), _f(3, 8, 18), _f(3, 12, 13)], 3),
        ([_f(4, 9, 12), _f(4, 9, 12)], 4),
        # Devuelve el PRIMER dia de la semana con el problema.
        ([_f(5, 9, 12), _f(5, 11, 13), _f(1, 9, 12), _f(1, 10, 11)], 1),
    ],
)
def test_primer_dia_con_franjas_superpuestas(
    franjas: list[dict[str, Any]], esperado: int | None
) -> None:
    assert first_overlapping_day(franjas) == esperado
