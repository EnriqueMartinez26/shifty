"""El WhatsApp de la tienda se lee con la misma regla que el front.

2026-10-03, decision de Mateo: una sena obligatoria se paga por Mercado Pago o
por WhatsApp, y una tienda que pide una sena obligatoria tiene que tener al
menos uno de los dos canales. El backend decide si el WhatsApp de la tienda
sirve con el mismo criterio que arma el link de wa.me en el front
(``frontend/src/shared/utils/whatsAppPhone.ts``): un numero que el front no
puede convertir en link no es un canal, porque el cliente no veria el boton.

Revision 4R de la PR #108 (R3 W4): los casos estaban copiados en los dos
tests y el NBSP los separaba (el front lo aceptaba, el back no). Ahora viven
en UN archivo, ``whatsAppPhone.cases.json``, que lee este test y
``whatsAppPhone.test.ts``, con casos de NBSP, espacio fino y BOM.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.whatsapp_phone import normalize_phone_for_whatsapp

_CASOS_PATH = (
    Path(__file__).resolve().parents[3]
    / "frontend"
    / "src"
    / "shared"
    / "utils"
    / "whatsAppPhone.cases.json"
)


def _casos() -> dict[str, Any]:
    if not _CASOS_PATH.exists():  # pragma: no cover - el repo completo lo trae
        pytest.fail(f"falta el archivo de casos compartido: {_CASOS_PATH}")
    return dict(json.loads(_CASOS_PATH.read_text(encoding="utf-8")))


CASOS = _casos()


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(caso["raw"], caso["expected"]) for caso in CASOS["normalizes"]],
)
def test_normaliza_como_el_front(raw: str, expected: str) -> None:
    assert normalize_phone_for_whatsapp(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [caso["raw"] for caso in CASOS["rejects"]],
    ids=[caso["case"] for caso in CASOS["rejects"]],
)
def test_sin_confianza_devuelve_none_como_el_front(raw: str) -> None:
    assert normalize_phone_for_whatsapp(raw) is None


def test_none_no_rompe() -> None:
    assert normalize_phone_for_whatsapp(None) is None


def test_los_casos_de_espacios_unicode_estan_en_el_archivo_compartido() -> None:
    """El hueco que encontro la revision no puede volver a quedar sin caso."""
    crudos = "".join(caso["raw"] for caso in CASOS["normalizes"])
    for espacio in ("\u00a0", "\u2009", "\ufeff"):
        assert espacio in crudos, f"falta un caso con {espacio!r}"
