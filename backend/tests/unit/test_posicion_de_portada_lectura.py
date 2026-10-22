"""Un valor ajeno en ``theme_config`` se lee como "sin elegir" (S10.1).

``cover_position`` solo lo escribe el PATCH validado, pero el JSON de tema no
tiene CHECK en la base: si un valor ajeno llegara a la fila, la respuesta tipada
(``Literal``) reventaria con 500 en el panel y en la vitrina publica.
"""

from typing import Any

import pytest

from modules.stores.model import Store


@pytest.mark.parametrize("posicion", ["top", "center", "bottom"])
def test_las_posiciones_validas_se_leen_tal_cual(posicion: str) -> None:
    assert Store(theme_config={"cover_position": posicion}).cover_position == posicion


@pytest.mark.parametrize(
    "theme", [None, {}, {"cover_position": None}, {"cover_position": "left"}]
)
def test_sin_valor_o_valor_ajeno_es_none(theme: dict[str, Any] | None) -> None:
    assert Store(theme_config=theme).cover_position is None
