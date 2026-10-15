"""Cotizacion de adicionales: pura, sin base ni framework.

Decision de Mateo (2026-10-14): un adicional suma PRECIO, nunca tiempo. La
misma funcion cotiza el preview de la sena (``/public/deposit/preview``) y el
alta publica, asi que lo que el cliente ve es lo que se cobra.

``price_selection`` recibe el catalogo del servicio (las filas de
``service_addons``, o cualquier objeto con los mismos atributos) y lo que eligio
el cliente, y devuelve las lineas con su importe y el total. Rechaza con
``AddonSelectionError`` un id desconocido, uno de otro servicio, uno repetido y
una cantidad fuera de 1..``max_quantity``: el llamador lo traduce a 422
``ADDON_UNAVAILABLE``.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Protocol

_CENT = Decimal("0.01")


class AddonSelectionError(Exception):
    """Lo elegido no corresponde al catalogo vigente del servicio."""


class CatalogAddon(Protocol):
    id: str
    service_id: str
    name: str
    unit_price: Decimal
    max_quantity: int


@dataclass(frozen=True)
class AddonChoice:
    """Lo que manda el cliente: un id de adicional y cuantos."""

    addon_id: str
    quantity: int


@dataclass(frozen=True)
class AddonLine:
    addon_id: str
    name: str
    unit_price: Decimal
    quantity: int
    amount: Decimal

    def snapshot(self) -> dict[str, str | int]:
        # Importes como texto, igual que ``DepositDecision.snapshot``: el JSON
        # de la base no tiene decimales exactos.
        return {
            "addon_id": self.addon_id,
            "name": self.name,
            "unit_price": str(self.unit_price),
            "quantity": self.quantity,
            "amount": str(self.amount),
        }


@dataclass(frozen=True)
class AddonsQuote:
    lines: tuple[AddonLine, ...] = ()

    @property
    def total(self) -> Decimal:
        return _money(sum((line.amount for line in self.lines), Decimal("0")))

    def snapshot(self) -> list[dict[str, str | int]] | None:
        """Lo que congela el turno; ``None`` sin adicionales."""
        return [line.snapshot() for line in self.lines] or None

    def label(self) -> str:
        """``Strass x6, Diseno x1`` para avisos y mails."""
        return ", ".join(f"{line.name} x{line.quantity}" for line in self.lines)


NO_ADDONS = AddonsQuote()


def _money(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def price_selection(
    catalog: Iterable[CatalogAddon],
    selection: Iterable[AddonChoice],
    *,
    service_id: str,
) -> AddonsQuote:
    """Cotiza lo elegido contra el catalogo del servicio ``service_id``."""
    by_id = {addon.id: addon for addon in catalog}
    seen: set[str] = set()
    lines: list[AddonLine] = []
    for choice in selection:
        addon = by_id.get(choice.addon_id)
        if addon is None or addon.service_id != service_id:
            raise AddonSelectionError(f"adicional desconocido: {choice.addon_id}")
        if choice.addon_id in seen:
            raise AddonSelectionError(f"adicional repetido: {choice.addon_id}")
        if not 1 <= choice.quantity <= addon.max_quantity:
            raise AddonSelectionError(f"cantidad fuera de rango: {choice.addon_id}")
        seen.add(choice.addon_id)
        unit_price = _money(Decimal(str(addon.unit_price)))
        lines.append(
            AddonLine(
                addon_id=addon.id,
                name=addon.name,
                unit_price=unit_price,
                quantity=choice.quantity,
                amount=_money(unit_price * choice.quantity),
            )
        )
    return AddonsQuote(tuple(lines))


def lines_from_snapshot(snapshot: object) -> list[dict[str, str | int]]:
    """Las lineas congeladas de un turno, tolerando un snapshot nulo o raro.

    El JSON no lo valida la base: una fila que no sea una lista de dicts se
    lee como "sin adicionales" en vez de romper una respuesta o un mail.
    """
    if not isinstance(snapshot, list):
        return []
    return [line for line in snapshot if isinstance(line, dict)]


def snapshot_label(snapshot: object) -> str:
    """``Strass x6`` a partir del snapshot congelado del turno."""
    return ", ".join(
        f"{line.get('name', '')} x{line.get('quantity', '')}"
        for line in lines_from_snapshot(snapshot)
    )
