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

from collections.abc import Sequence
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
    """Resumen agregado del cliente en ESTA tienda (una sola consulta).

    ``known=False`` significa "no sabemos": el telefono no paso por OTP, asi
    que no es de nadie en particular. No es lo mismo que un cliente nuevo, y
    por eso no dispara los recargos por historial: si no, quien tipea el
    telefono de otro le carga (o hereda) sus antecedentes, y el preview se
    volvia un oraculo de la cartera de la tienda.
    """

    completed: int = 0
    absent: int = 0
    cancelled: int = 0
    known: bool = True

    @property
    def is_new(self) -> bool:
        return (
            self.known
            and self.completed == 0
            and self.absent == 0
            and self.cancelled == 0
        )


UNKNOWN_HISTORY = ClientHistory(known=False)


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
        # El tope va aca y no solo en `decide_deposit` (que acota recien al
        # sumar recargos): una fila vieja con `percent` = 500 cobraba 5 veces
        # el precio por adelantado, porque con recargo 0 el importe salia sin
        # acotar (AUD2-B6-03, 2026-09-20). `fixed` ya hacia lo mismo. La
        # garantia contra que esa fila exista es el CHECK
        # `ck_services_deposit_percent_max`; esto protege a las que ya estan.
        return min(price, _money(price * configured / Decimal("100")))
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
    if rules.absent_client_extra_percent > 0 and history.known and history.absent > 0:
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


# ---------------------------------------------------------------------------
# Varios servicios en un turno (decision de Mateo, 2026-10-16)
# ---------------------------------------------------------------------------

_MODE_RANK = {"none": 0, "optional": 1, "required": 2}


def selection_deposit_mode(services: Sequence[Any]) -> str:
    """El modo de sena del turno: ``required`` si algun servicio la exige, si
    no ``optional`` si alguno la ofrece, si no ``none``. Con un servicio, su
    modo (``deposit_channels.deposit_mode_of``)."""
    modo = "none"
    for service in services:
        candidato = str(getattr(service, "deposit_mode", "none") or "none")
        if _MODE_RANK.get(candidato, 0) > _MODE_RANK.get(modo, 0):
            modo = candidato
    return modo


@dataclass(frozen=True)
class SelectionDeposit:
    """La sena de un turno de uno o varios servicios y de donde salio."""

    decision: DepositDecision
    # El servicio cuya regla dio el maximo; None si ninguno pide sena.
    rule_service: Any | None


def decide_selection_deposit(
    services: Sequence[Any],
    *,
    price: Decimal,
    notice: timedelta,
    rules: DepositRules,
    history: ClientHistory,
) -> SelectionDeposit:
    """Sena SOBRE EL TOTAL del turno: la regla mas alta entre sus servicios.

    Decision de Mateo (2026-10-16): si al menos un servicio elegido tiene sena
    (``required`` u ``optional``), la sena se calcula sobre ``price``, el TOTAL
    del turno (todos los servicios y todos los adicionales, con la promo), con
    la regla de cada servicio que la tiene, y se cobra la mayor. Los recargos
    por antelacion e historial son los de esa regla (``decide_deposit``). Un
    empate lo gana el que se eligio primero (el principal antes que los
    extras). Ejemplo: Corte $10.000 con 50% + Barba $5.000 sin sena -> $7.500.

    Con un solo servicio es exactamente ``decide_deposit`` de ese servicio.
    """
    if not services:
        raise ValueError("un turno tiene al menos un servicio")
    mejor: DepositDecision | None = None
    regla: Any | None = None
    for service in services:
        if str(getattr(service, "deposit_mode", "none") or "none") == "none":
            continue
        decision = decide_deposit(
            service, price=price, notice=notice, rules=rules, history=history
        )
        if mejor is None or decision.amount > mejor.amount:
            mejor, regla = decision, service
    if mejor is None:
        # Ningun servicio pide sena: la misma decision vacia de siempre.
        return SelectionDeposit(
            decide_deposit(
                services[0], price=price, notice=notice, rules=rules, history=history
            ),
            None,
        )
    return SelectionDeposit(mejor, regla)
