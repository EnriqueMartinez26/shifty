from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.feature_flags import is_store_feature_enabled
from core.validation import PUBLIC_ID_PATTERN
from modules.auth.dependencies import get_current_user
from modules.ledger.model import CustomerLedger, LedgerMovementType
from modules.ledger.schemas import (
    CustomerLedgerResponse,
    LedgerMovementCreate,
    LedgerMovementResponse,
)
from modules.stores.model import Store
from modules.users.model import User, UserRole

router = APIRouter(prefix="/ledger", tags=["Customer Ledger"])
PublicIdPath = Annotated[str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)]


def _require_financial_access(user: User) -> None:
    if user.role not in (UserRole.ADMIN, UserRole.STAFF) and not user.is_global_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tenés permiso para ver deuda")


async def _ensure_ledger_feature_enabled(db: AsyncSession, user: User) -> None:
    result = await db.execute(select(Store).where(Store.id == user.store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise HTTPException(status_code=404, detail="Tienda no encontrada")
    if not is_store_feature_enabled(store.feature_flags, "ledger"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La funcionalidad de deuda no está habilitada para esta tienda",
        )


def _signed_amount(movement_type: str, amount: Decimal) -> Decimal:
    if movement_type in {LedgerMovementType.PAYMENT.value, LedgerMovementType.REFUND.value}:
        return -amount
    return amount


@router.get("/customers/{client_id}", response_model=CustomerLedgerResponse)
async def get_customer_ledger(
    client_id: PublicIdPath,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_financial_access(user)
    await _ensure_ledger_feature_enabled(db, user)
    result = await db.execute(
        select(CustomerLedger)
        .where(CustomerLedger.store_id == user.store_id, CustomerLedger.client_id == client_id)
        .order_by(CustomerLedger.created_at.asc())
    )
    movements = list(result.scalars().all())
    balance = movements[-1].balance_after if movements else Decimal("0.00")
    return CustomerLedgerResponse(
        client_id=client_id,
        balance=balance,
        movements=[
            LedgerMovementResponse(
                public_id=item.id,
                movement_type=item.movement_type,
                amount=item.amount,
                balance_after=item.balance_after,
                appointment_id=item.appointment_id,
                notes=item.notes,
                created_at=item.created_at,
            )
            for item in movements
        ],
    )


@router.post("/customers/{client_id}/movements", response_model=LedgerMovementResponse)
async def add_customer_ledger_movement(
    client_id: PublicIdPath,
    data: LedgerMovementCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_financial_access(user)
    await _ensure_ledger_feature_enabled(db, user)
    result = await db.execute(
        select(CustomerLedger)
        .where(CustomerLedger.store_id == user.store_id, CustomerLedger.client_id == client_id)
        .order_by(CustomerLedger.created_at.desc())
        .limit(1)
    )
    previous = result.scalar_one_or_none()
    previous_balance = previous.balance_after if previous else Decimal("0.00")
    balance_after = previous_balance + _signed_amount(data.movement_type, data.amount)
    movement = CustomerLedger(
        store_id=user.store_id,
        client_id=client_id,
        appointment_id=data.appointment_id,
        movement_type=data.movement_type,
        amount=data.amount,
        balance_after=balance_after,
        notes=data.notes,
    )
    db.add(movement)
    await db.commit()
    await db.refresh(movement)
    return LedgerMovementResponse(
        public_id=movement.id,
        movement_type=movement.movement_type,
        amount=movement.amount,
        balance_after=movement.balance_after,
        appointment_id=movement.appointment_id,
        notes=movement.notes,
        created_at=movement.created_at,
    )
