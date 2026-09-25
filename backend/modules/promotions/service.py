from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppException, ValidationException
from core.utils import ensure_utc_aware
from modules.promotions.model import PromotionRedemption, StorePromotion
from modules.promotions.schemas import PromotionCreate, PromotionUpdate
from modules.services.model import Service
from modules.users.model import User


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _aware(value: datetime | None) -> datetime | None:
    return ensure_utc_aware(value) if value is not None else None


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
    # SQLite devuelve la vigencia naive aun con DateTime(timezone=True): sin
    # normalizar, comparar contra `now` (aware) revienta con TypeError.
    if promotion.valid_from and ensure_utc_aware(promotion.valid_from) > now:
        return "La promocion todavia no esta vigente"
    if promotion.valid_until and ensure_utc_aware(promotion.valid_until) < now:
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
    # Con el indice unico parcial (B2-14) un codigo puede repetirse entre una
    # promocion activa y varias dadas de baja: manda la activa; si no hay,
    # la baja mas reciente (asi el canje sigue diciendo "no esta activa" en
    # vez de reventar con MultipleResultsFound).
    statement = (
        select(StorePromotion)
        .where(
            StorePromotion.store_id == store_id,
            StorePromotion.code == code,
        )
        .order_by(StorePromotion.is_active.desc(), StorePromotion.created_at.desc())
        .limit(1)
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


def _assert_codigo_libre(existente: StorePromotion | None) -> None:
    if existente is not None:
        raise AppException(
            message="Ya existe una promocion con ese codigo",
            http_status=409,
            error_code="PROMOTION_CODE_DUPLICATE",
        )


async def create_store_promotion(
    db: AsyncSession, *, store_id: str, data: PromotionCreate
) -> StorePromotion:
    """Alta de una promocion. Dueña de la transaccion (CLAUDE.md §2)."""
    if data.is_active:
        duplicate = await db.execute(
            select(StorePromotion).where(
                StorePromotion.store_id == store_id,
                StorePromotion.code == data.code,
                StorePromotion.is_active.is_(True),
            )
        )
        _assert_codigo_libre(duplicate.scalar_one_or_none())

    promotion = StorePromotion(store_id=store_id, **data.model_dump())
    db.add(promotion)
    await db.commit()
    await db.refresh(promotion)
    return promotion


async def update_store_promotion(
    db: AsyncSession, *, promotion: StorePromotion, data: PromotionUpdate
) -> StorePromotion:
    """Edicion parcial: valida codigo, tope porcentual y ventana, y persiste."""
    payload = data.model_dump(exclude_unset=True)

    # Solo compite por el codigo una promocion que queda activa: cambiarle el
    # codigo o reactivarla no puede pisar a otra activa con el mismo codigo.
    candidate_code = payload.get("code") or promotion.code
    candidate_active = payload.get("is_active", promotion.is_active)
    toca_unicidad = candidate_code != promotion.code or (
        candidate_active and not promotion.is_active
    )
    if candidate_active and toca_unicidad:
        duplicate = await db.execute(
            select(StorePromotion).where(
                StorePromotion.store_id == promotion.store_id,
                StorePromotion.code == candidate_code,
                StorePromotion.id != promotion.id,
                StorePromotion.is_active.is_(True),
            )
        )
        _assert_codigo_libre(duplicate.scalar_one_or_none())

    candidate_type = payload.get("promotion_type", promotion.promotion_type)
    candidate_value = payload.get("value", promotion.value)
    if (
        candidate_type == "percent"
        and candidate_value is not None
        and candidate_value > 100
    ):
        raise ValidationException("El descuento porcentual no puede superar 100")

    # El payload llega aware (lo exige el schema) y lo guardado puede venir
    # naive de SQLite: compararlos crudos levanta TypeError -> 500.
    candidate_valid_from = _aware(payload.get("valid_from", promotion.valid_from))
    candidate_valid_until = _aware(payload.get("valid_until", promotion.valid_until))
    if (
        candidate_valid_from
        and candidate_valid_until
        and candidate_valid_from >= candidate_valid_until
    ):
        raise ValidationException("La vigencia de la promocion es invalida")

    for key, value in payload.items():
        setattr(promotion, key, value)

    await db.commit()
    await db.refresh(promotion)
    return promotion


async def deactivate_store_promotion(
    db: AsyncSession, *, promotion: StorePromotion
) -> None:
    """Baja logica: la promocion puede tener canjes historicos asociados."""
    promotion.is_active = False
    await db.commit()
