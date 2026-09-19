"""El sobre de error lo arma `error_payload`, no un modelo sin uso (X-17).

2026-09-18. Sintoma: `core/responses.py` declaraba `class ApiError(BaseModel)`
con la forma del sobre de error, pero nada la importaba: ni los handlers de
`main.py` (usan `error_response`), ni ningun `responses=` de FastAPI, ni los
tests. Dos definiciones de la misma forma, una viva y otra decorativa, pueden
divergir sin que nada avise.

La regla 20 (errores neutros hacia afuera) la sostienen `error_payload` /
`error_response` y los handlers de `main.py`. Este test fija la forma que
`ApiError` describia sobre la funcion que de verdad la produce.
"""

from __future__ import annotations

import core.responses
from core.responses import error_payload, is_canonical_payload


def test_core_responses_no_expone_api_error() -> None:
    assert not hasattr(core.responses, "ApiError")


def test_el_sobre_de_error_tiene_la_forma_documentada() -> None:
    """Forma de docs/API_EXTERNAL_CLIENT_TEMPLATE.md §3.3."""
    sobre = error_payload("APPOINTMENT_CONFLICT", "Ocupado.", {"a": 1})

    assert sobre == {
        "success": False,
        "error_code": "APPOINTMENT_CONFLICT",
        "message": "Ocupado.",
        "detail": {"a": 1},
    }
    assert is_canonical_payload(sobre)


def test_sin_detalle_el_sobre_no_lo_inventa() -> None:
    assert error_payload("X", "m") == {
        "success": False,
        "error_code": "X",
        "message": "m",
    }
