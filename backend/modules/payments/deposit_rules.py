"""Regla de la sena: cuanto se cobra y por que. Pura, sin base ni framework.

La sena base la define el servicio (porcentaje, fijo o total). La tienda
puede sumarle recargos, en puntos porcentuales del precio, donde el riesgo
de ausencia es mayor:

- reservas hechas con mucha antelacion (a partir de N dias);
- cliente sin historial en la tienda;
- cliente con ausencias previas.

El resultado nunca supera el precio y nunca crea una sena donde el servicio
no la tiene. Se evalua UNA vez por reserva (mismo ``now``, mismo historial)
y el motivo viaja hasta el pago como snapshot. Nada de cancelaciones ni
reembolsos: eso es de la tienda.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

REASON_BASE = "base"
REASON_FAR_NOTICE = "far_notice"
REASON_NEW_CLIENT = "new_client"
REASON_ABSENCES = "absences"


@dataclass(frozen=True)
class DepositRules:
    """Configuracion de la tienda (columnas con CHECK en ``stores``)."""

    far_notice_days: int = 0
    far_notice_extra_percent: int = 0
    new_client_extra_percent: int = 0
    absent_client_extra_percent: int = 0

    @classmethod
    def from_store(cls, store: Any) -> "DepositRules":
        return cls(
            far_notice_days=int(getattr(store, "deposit_far_notice_days", 0) or 0),
            far_notice_extra_percent=int(
                getattr(store, "deposit_far_notice_extra_percent", 0) or 0
            ),
            new_client_extra_percent=int(
                getattr(store, "deposit_new_client_extra_percent", 0) or 0
            ),
            absent_client_extra_percent=int(
                getattr(store, "deposit_absent_client_extra_percent", 0) or 0
            ),
        )


@dataclass(frozen=True)
class ClientHistory:
    """Resumen agregado del cliente en ESTA tienda (una sola consulta)."""

    completed: int = 0
    absent: int = 0
    cancelled: int = 0

    @property
    def is_new(self) -> bool:
        return self.completed == 0 and self.absent == 0 and self.cancelled == 0


@dataclass(frozen=True)
class DepositDecision:
    amount: Decimal
    base_amount: Decimal
    extra_percent: int
    reasons: list[str] = field(default_factory=list)

    def snapshot(self) -> dict[str, Any]:
        return {
            "amount": str(self.amount),
            "base_amount": str(self.base_amount),
            "extra_percent": self.extra_percent,
            "reasons": list(self.reasons),
        }


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def base_deposit(service: Any, price: Decimal) -> Decimal:
    """Sena base del servicio sobre ``price`` (que puede traer promo)."""
    mode = getattr(service, "deposit_mode", "none") or "none"
    payment_type = getattr(service, "deposit_type", "percent") or "percent"
    raw_amount = getattr(service, "deposit_amount", None)
    price = _money(price)
    if mode == "none" or price <= 0:
        return Decimal("0.00")
    if payment_type == "full":
        return price
    if raw_amount is None:
        return Decimal("0.00")
    configured = _money(Decimal(str(raw_amount)))
    if payment_type == "fixed":
        return min(configured, price)
    if payment_type == "percent":
        return _money(price * configured / Decimal("100"))
    return Decimal("0.00")


def decide_deposit(
    service: Any,
    *,
    price: Decimal,
    notice: timedelta,
    rules: DepositRules,
    history: ClientHistory,
) -> DepositDecision:
    base = base_deposit(service, price)
    price = _money(price)
    if base <= 0:
        # Sin sena base no hay recargo: el servicio no cobra sena y punto.
        return DepositDecision(
            amount=Decimal("0.00"), base_amount=base, extra_percent=0
        )

    extra = 0
    reasons = [REASON_BASE]
    if rules.far_notice_days > 0 and notice >= timedelta(days=rules.far_notice_days):
        extra += rules.far_notice_extra_percent
        reasons.append(REASON_FAR_NOTICE)
    if rules.new_client_extra_percent > 0 and history.is_new:
        extra += rules.new_client_extra_percent
        reasons.append(REASON_NEW_CLIENT)
    if rules.absent_client_extra_percent > 0 and history.absent > 0:
        extra += rules.absent_client_extra_percent
        reasons.append(REASON_ABSENCES)

    if extra <= 0:
        return DepositDecision(
            amount=base, base_amount=base, extra_percent=0, reasons=reasons
        )
    amount = min(price, _money(base + price * Decimal(extra) / Decimal("100")))
    return DepositDecision(
        amount=amount, base_amount=base, extra_percent=extra, reasons=reasons
    )
