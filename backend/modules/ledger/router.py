from decimal import Decimal
from typing import Annotated

from fastapi import Depends, Path
from core.router import CanonicalAPIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.exceptions import FeatureDisabledException, PermissionDeniedException, StoreNotFoundException
from core.feature_flags import is_store_feature_enabled
from core.validation import PUBLIC_ID_PATTERN
from modules.auth.dependencies import get_current_user
from modules.ledger.model import CustomerLedger, LedgerMovementType
from modules.ledger.schemas import (
    CustomerLedgerResponse,
    LedgerMovementCreate,
    LedgerMovementResponse,
    LedgerSummaryClientItem,
    LedgerSummaryResponse,
)
from modules.stores.model import Store
from modules.users.model import User, UserRole

router = CanonicalAPIRouter(prefix="/ledger", tags=["Customer Ledger"])
PublicIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]


def _require_financial_access(user: User) -> None:
    if user.role not in (UserRole.ADMIN, UserRole.STAFF) and not user.is_global_admin:
        raise PermissionDeniedException("ver deudas")


async def _ensure_ledger_feature_enabled(db: AsyncSession, user: User) -> None:
    result = await db.execute(select(Store).where(Store.id == user.store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise StoreNotFoundException(user.store_id)
    if not is_store_feature_enabled(store.feature_flags, "ledger"):
        raise FeatureDisabledException("deuda")


def _signed_amount(movement_type: str, amount: Decimal) -> Decimal:
    if movement_type in {
        LedgerMovementType.PAYMENT.value,
        LedgerMovementType.REFUND.value,
    }:
        return -amount
    return amount


def _client_display_name(user: User | None, *, fallback_id: str) -> str:
    if user:
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        if full_name:
            return full_name
        if user.email:
            return user.email
        if user.phone:
            return user.phone
    return fallback_id


@router.get("/summary", response_model=LedgerSummaryResponse)
async def get_ledger_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_financial_access(user)
    await _ensure_ledger_feature_enabled(db, user)
    result = await db.execute(
        select(CustomerLedger)
        .where(CustomerLedger.store_id == user.store_id)
        .order_by(CustomerLedger.client_id.asc(), CustomerLedger.created_at.asc())
    )
    movements = list(result.scalars().all())
    latest_by_client: dict[str, CustomerLedger] = {}
    for movement in movements:
        latest_by_client[movement.client_id] = movement

    debt_rows = [
        movement
        for movement in latest_by_client.values()
        if Decimal(str(movement.balance_after or 0)) > 0
    ]
    client_ids = [movement.client_id for movement in debt_rows]
    users_by_id: dict[str, User] = {}
    if client_ids:
        users_result = await db.execute(select(User).where(User.id.in_(client_ids)))
        users_by_id = {
            customer.id: customer for customer in users_result.scalars().all()
        }

    total_balance = sum(
        (Decimal(str(item.balance_after or 0)) for item in debt_rows), Decimal("0.00")
    )
    average_balance = (total_balance / len(debt_rows)) if debt_rows else Decimal("0.00")
    top_debtors = sorted(
        debt_rows,
        key=lambda item: (Decimal(str(item.balance_after or 0)), item.created_at),
        reverse=True,
    )[:5]

    return LedgerSummaryResponse(
        total_balance=total_balance,
        debtors_count=len(debt_rows),
        average_balance=average_balance.quantize(Decimal("0.01")),
        total_movements=len(movements),
        top_debtors=[
            LedgerSummaryClientItem(
                client_id=item.client_id,
                client_name=_client_display_name(
                    users_by_id.get(item.client_id), fallback_id=item.client_id
                ),
                balance=Decimal(str(item.balance_after or 0)).quantize(Decimal("0.01")),
                last_movement_at=item.created_at,
            )
            for item in top_debtors
        ],
    )


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
        .where(
            CustomerLedger.store_id == user.store_id,
            CustomerLedger.client_id == client_id,
        )
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
        .where(
            CustomerLedger.store_id == user.store_id,
            CustomerLedger.client_id == client_id,
        )
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
