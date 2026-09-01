from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Path, Query, status
from core.router import CanonicalAPIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.exceptions import (
    AppException,
    PermissionDeniedException,
    ResourceNotFoundException,
    ServiceNotFoundException,
    ValidationException,
)
from core.validation import PUBLIC_ID_PATTERN
from modules.auth.dependencies import get_current_user
from modules.promotions.model import StorePromotion
from modules.promotions.schemas import (
    PromotionCreate,
    PromotionQuoteResponse,
    PromotionResponse,
    PromotionUpdate,
)
from modules.promotions.service import quote_promotion
from modules.services.model import Service
from modules.users.model import User, UserRole

router = CanonicalAPIRouter(prefix="/promotions", tags=["Promotions"])
PublicIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]
PublicIdQuery = Annotated[
    str, Query(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]


def _require_admin(user: User) -> None:
    if user.role != UserRole.ADMIN and not user.is_global_admin:
        raise PermissionDeniedException("gestionar promociones")


def _serialize_promotion(promotion: StorePromotion) -> PromotionResponse:
    return PromotionResponse(
        public_id=promotion.id,
        code=promotion.code,
        title=promotion.title,
        description=promotion.description,
        promotion_type=promotion.promotion_type,
        value=promotion.value,
        min_service_amount=promotion.min_service_amount,
        max_uses=promotion.max_uses,
        current_uses=promotion.current_uses,
        valid_from=promotion.valid_from,
        valid_until=promotion.valid_until,
        is_active=promotion.is_active,
        created_at=promotion.created_at,
        updated_at=promotion.updated_at,
    )


async def _get_store_promotion_or_404(
    db: AsyncSession, promotion_public_id: str, store_id: str
) -> StorePromotion:
    result = await db.execute(
        select(StorePromotion).where(
            StorePromotion.id == promotion_public_id,
            StorePromotion.store_id == store_id,
        )
    )
    promotion = result.scalar_one_or_none()
    if not promotion:
        raise ResourceNotFoundException("Promocion", promotion_public_id)
    return promotion


@router.get("/", response_model=list[PromotionResponse])
async def list_promotions(
    include_inactive: bool = Query(default=True),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[PromotionResponse]:
    _require_admin(user)
    statement = select(StorePromotion).where(StorePromotion.store_id == user.store_id)
    if not include_inactive:
        statement = statement.where(StorePromotion.is_active.is_(True))
    result = await db.execute(statement.order_by(StorePromotion.created_at.desc()))
    return [_serialize_promotion(promotion) for promotion in result.scalars().all()]


@router.post("/", response_model=PromotionResponse, status_code=status.HTTP_201_CREATED)
async def create_promotion(
    data: PromotionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PromotionResponse:
    _require_admin(user)
    duplicate = await db.execute(
        select(StorePromotion).where(
            StorePromotion.store_id == user.store_id,
            StorePromotion.code == data.code,
        )
    )
    if duplicate.scalar_one_or_none():
        raise AppException(
            message="Ya existe una promocion con ese codigo",
            http_status=409,
            error_code="PROMOTION_CODE_DUPLICATE",
        )

    promotion = StorePromotion(store_id=user.store_id, **data.model_dump())
    db.add(promotion)
    await db.commit()
    await db.refresh(promotion)
    return _serialize_promotion(promotion)


@router.patch("/{promotion_public_id}", response_model=PromotionResponse)
async def update_promotion(
    promotion_public_id: PublicIdPath,
    data: PromotionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PromotionResponse:
    _require_admin(user)
    promotion = await _get_store_promotion_or_404(
        db, promotion_public_id, user.store_id
    )
    payload = data.model_dump(exclude_unset=True)

    candidate_code = payload.get("code")
    if candidate_code and candidate_code != promotion.code:
        duplicate = await db.execute(
            select(StorePromotion).where(
                StorePromotion.store_id == user.store_id,
                StorePromotion.code == candidate_code,
                StorePromotion.id != promotion.id,
            )
        )
        if duplicate.scalar_one_or_none():
            raise AppException(
                message="Ya existe una promocion con ese codigo",
                http_status=409,
                error_code="PROMOTION_CODE_DUPLICATE",
            )

    candidate_type = payload.get("promotion_type", promotion.promotion_type)
    candidate_value = payload.get("value", promotion.value)
    if (
        candidate_type == "percent"
        and candidate_value is not None
        and candidate_value > 100
    ):
        raise ValidationException("El descuento porcentual no puede superar 100")

    candidate_valid_from = payload.get("valid_from", promotion.valid_from)
    candidate_valid_until = payload.get("valid_until", promotion.valid_until)
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
    return _serialize_promotion(promotion)


@router.delete("/{promotion_public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_promotion(
    promotion_public_id: PublicIdPath,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Da de baja una promocion.

    Es un borrado logico (is_active=False): la promocion puede tener canjes
    historicos asociados a turnos, y un borrado fisico romperia esa trazabilidad.
    Deja de estar disponible para nuevos canjes de inmediato.
    """
    _require_admin(user)
    promotion = await _get_store_promotion_or_404(
        db, promotion_public_id, user.store_id
    )
    promotion.is_active = False
    await db.commit()


@router.get("/preview", response_model=PromotionQuoteResponse)
async def preview_promotion(
    service_id: PublicIdQuery,
    code: Annotated[str, Query(min_length=3, max_length=30)],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> PromotionQuoteResponse:
    result = await db.execute(
        select(Service).where(
            Service.public_id == service_id,
            Service.store_id == user.store_id,
            Service.is_active.is_(True),
        )
    )
    service = result.scalar_one_or_none()
    if not service:
        raise ServiceNotFoundException(service_id)

    _promotion, quote, error = await quote_promotion(
        db,
        store_id=user.store_id,
        service=service,
        code=code,
    )
    if not quote:
        raise ValidationException(error or "Promocion invalida")

    return PromotionQuoteResponse(
        code=quote.code,
        title=quote.title,
        promotion_type=quote.promotion_type,
        base_amount=quote.base_amount,
        discount_amount=quote.discount_amount,
        final_amount=quote.final_amount,
    )
