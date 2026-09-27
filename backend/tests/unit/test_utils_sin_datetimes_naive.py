"""`core.utils` no ofrece como pasar un instante a naive (X-15, 2026-09-18).

Sintoma: `to_utc_naive` ("para DBs antiguas o legacy") era la unica funcion
del repo que producia datetimes sin zona, contra la regla 24 (persistencia y
calculo en UTC aware). No la llamaba nadie: la direccion que el repo adopto es
la inversa, `ensure_utc_aware`, que interpreta como UTC lo que SQLite devuelve
naive. Dejarla invitaba a usarla.
"""

from __future__ import annotations

from datetime import datetime, timezone

import core.utils
from core.utils import ensure_utc_aware


def test_core_utils_no_expone_to_utc_naive() -> None:
    assert not hasattr(core.utils, "to_utc_naive")


def test_la_conversion_que_queda_es_hacia_aware() -> None:
    """Regla 24: lo que sale de la base naive (SQLite) se lee como UTC."""
    naive = datetime(2026, 9, 18, 12, 0)

    assert ensure_utc_aware(naive) == datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)
