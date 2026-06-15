from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.promotions.model import PromotionRedemption, StorePromotion
from modules.services.model import Service
from modules.users.model import User


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def normalize_promotion_code(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().upper()
    return normalized or None


@dataclass(slots=True)
class PromotionQuote:
    code: str
    title: str
    promotion_type: str
    base_amount: Decimal
    discount_amount: Decimal
    final_amount: Decimal


def _validate_promotion_window(
    promotion: StorePromotion, base_amount: Decimal
) -> str | None:
    now = datetime.now(timezone.utc)
    if not promotion.is_active:
        return "La promocion no esta activa"
    if promotion.valid_from and promotion.valid_from > now:
        return "La promocion todavia no esta vigente"
    if promotion.valid_until and promotion.valid_until < now:
        return "La promocion ya vencio"
    if promotion.max_uses is not None and promotion.current_uses >= promotion.max_uses:
        return "La promocion ya alcanzo su limite de usos"
    if promotion.min_service_amount is not None and base_amount < Decimal(
        str(promotion.min_service_amount)
    ):
        return "La promocion no aplica a este servicio"
    return None


def _calculate_discount(base_amount: Decimal, promotion: StorePromotion) -> Decimal:
    raw_value = _money(Decimal(str(promotion.value)))
    if promotion.promotion_type == "percent":
        return min(_money(base_amount * raw_value / Decimal("100")), base_amount)
    return min(raw_value, base_amount)


async def get_store_promotion(
    db: AsyncSession,
    *,
    store_id: str,
    code: str,
    for_update: bool = False,
) -> StorePromotion | None:
    statement = select(StorePromotion).where(
        StorePromotion.store_id == store_id,
        StorePromotion.code == code,
    )
    if for_update:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    return result.scalar_one_or_none()


async def quote_promotion(
    db: AsyncSession,
    *,
    store_id: str,
    service: Service,
    code: str,
    for_update: bool = False,
) -> tuple[StorePromotion | None, PromotionQuote | None, str | None]:
    normalized_code = normalize_promotion_code(code)
    if not normalized_code:
        return None, None, "Codigo de promocion invalido"

    promotion = await get_store_promotion(
        db, store_id=store_id, code=normalized_code, for_update=for_update
    )
    if not promotion:
        return None, None, "No encontramos una promocion con ese codigo"

    base_amount = _money(Decimal(str(service.price or 0)))
    validation_error = _validate_promotion_window(promotion, base_amount)
    if validation_error:
        return promotion, None, validation_error

    discount_amount = _calculate_discount(base_amount, promotion)
    quote = PromotionQuote(
        code=promotion.code,
        title=promotion.title,
        promotion_type=promotion.promotion_type,
        base_amount=base_amount,
        discount_amount=discount_amount,
        final_amount=_money(base_amount - discount_amount),
    )
    return promotion, quote, None


async def redeem_promotion(
    db: AsyncSession,
    *,
    store_id: str,
    appointment_id: str,
    client: User | None,
    service: Service,
    code: str,
) -> PromotionQuote:
    promotion, quote, error = await quote_promotion(
        db,
        store_id=store_id,
        service=service,
        code=code,
        for_update=True,
    )
    if not promotion or not quote:
        raise ValueError(error or "Promocion invalida")

    promotion.current_uses += 1
    db.add(
        PromotionRedemption(
            store_id=store_id,
            promotion_id=promotion.id,
            appointment_id=appointment_id,
            client_id=client.id if client else None,
            code_snapshot=quote.code,
            title_snapshot=quote.title,
            promotion_type_snapshot=quote.promotion_type,
            value_snapshot=promotion.value,
            base_amount=quote.base_amount,
            discount_amount=quote.discount_amount,
            final_amount=quote.final_amount,
        )
    )
    return quote
