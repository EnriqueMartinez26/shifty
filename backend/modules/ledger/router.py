from decimal import ROUND_HALF_EVEN, Decimal
from typing import Annotated

from fastapi import Depends, Path
from core.router import CanonicalAPIRouter
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.exceptions import (
    FeatureDisabledException,
    PermissionDeniedException,
    StoreNotFoundException,
)
from core.feature_flags import is_store_feature_enabled
from core.validation import PUBLIC_ID_PATTERN
from modules.auth.dependencies import get_current_user
from modules.ledger.model import CustomerLedger
from modules.ledger.schemas import (
    CustomerLedgerResponse,
    LedgerMovementCreate,
    LedgerMovementResponse,
    LedgerSummaryClientItem,
    LedgerSummaryResponse,
)
from modules.ledger.service import add_movement, reverse_movement
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
) -> LedgerSummaryResponse:
    _require_financial_access(user)
    await _ensure_ledger_feature_enabled(db, user)
    # La deuda vigente de un cliente es su ULTIMO movimiento (balance_after es
    # un saldo incremental). La DB se queda con uno por cliente (row_number
    # sobre la particion por client_id) y agrega ahi mismo: total, cantidad y
    # promedio con SUM/COUNT/AVG, y el top 5 con ORDER BY ... LIMIT. Antes la
    # lista entera de deudores viajaba al proceso y se sumaba en Python
    # (regla 11; 2026-09-16, B2-06).
    ultimo_por_cliente = (
        select(
            CustomerLedger.id.label("id"),
            func.row_number()
            .over(
                partition_by=CustomerLedger.client_id,
                order_by=CustomerLedger.created_at.desc(),
            )
            .label("rn"),
        )
        .where(CustomerLedger.store_id == user.store_id)
        .subquery()
    )
    deuda_vigente = (
        select(
            CustomerLedger.client_id.label("client_id"),
            CustomerLedger.balance_after.label("balance_after"),
            CustomerLedger.created_at.label("created_at"),
        )
        .join(ultimo_por_cliente, CustomerLedger.id == ultimo_por_cliente.c.id)
        .where(ultimo_por_cliente.c.rn == 1, CustomerLedger.balance_after > 0)
        .subquery()
    )
    total_balance, debtors_count, average_balance = (
        await db.execute(
            select(
                func.coalesce(func.sum(deuda_vigente.c.balance_after), 0),
                func.count(),
                func.avg(deuda_vigente.c.balance_after),
            ).select_from(deuda_vigente)
        )
    ).one()
    total_movements = int(
        await db.scalar(
            select(func.count())
            .select_from(CustomerLedger)
            .where(CustomerLedger.store_id == user.store_id)
        )
        or 0
    )
    # El nombre sale del mismo JOIN, acotado a clientes de ESTA tienda: un
    # client_id ajeno cae al fallback en vez de leer users de otra tienda.
    top_result = await db.execute(
        select(deuda_vigente, User)
        .select_from(
            deuda_vigente.outerjoin(
                User,
                and_(
                    User.id == deuda_vigente.c.client_id,
                    User.store_id == user.store_id,
                ),
            )
        )
        .order_by(
            deuda_vigente.c.balance_after.desc(), deuda_vigente.c.created_at.desc()
        )
        .limit(5)
    )

    return LedgerSummaryResponse(
        total_balance=Decimal(str(total_balance or 0)).quantize(Decimal("0.01")),
        debtors_count=int(debtors_count or 0),
        # AVG redondea distinto segun el motor (numeric en Postgres, float en
        # SQLite): el redondeo se fija aca, explicito, a 2 decimales y con la
        # misma regla (half-even) que usaba la division en Python.
        average_balance=Decimal(str(average_balance or 0)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_EVEN
        ),
        total_movements=total_movements,
        top_debtors=[
            LedgerSummaryClientItem(
                client_id=client_id,
                client_name=_client_display_name(customer, fallback_id=client_id),
                balance=Decimal(str(balance_after)).quantize(Decimal("0.01")),
                last_movement_at=created_at,
            )
            for client_id, balance_after, created_at, customer in top_result.all()
        ],
    )


@router.get("/customers/{client_id}", response_model=CustomerLedgerResponse)
async def get_customer_ledger(
    client_id: PublicIdPath,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CustomerLedgerResponse:
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
) -> LedgerMovementResponse:
    _require_financial_access(user)
    await _ensure_ledger_feature_enabled(db, user)
    movement = await add_movement(
        db,
        store_id=user.store_id,
        client_id=client_id,
        movement_type=data.movement_type,
        amount=data.amount,
        appointment_id=data.appointment_id,
        notes=data.notes,
    )
    return LedgerMovementResponse(
        public_id=movement.id,
        movement_type=movement.movement_type,
        amount=movement.amount,
        balance_after=movement.balance_after,
        appointment_id=movement.appointment_id,
        notes=movement.notes,
        created_at=movement.created_at,
    )


@router.post(
    "/customers/{client_id}/movements/{movement_id}/reverse",
    response_model=LedgerMovementResponse,
)
async def reverse_customer_ledger_movement(
    client_id: PublicIdPath,
    movement_id: PublicIdPath,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> LedgerMovementResponse:
    """Anula un movimiento cargado por error.

    No borra el original (rompe la trazabilidad del saldo): agrega un
    movimiento de ajuste que compensa su efecto y deja el saldo como si el
    movimiento erroneo nunca hubiera existido. Cada movimiento se puede
    revertir una sola vez.
    """
    _require_financial_access(user)
    await _ensure_ledger_feature_enabled(db, user)
    reversal = await reverse_movement(
        db,
        store_id=user.store_id,
        client_id=client_id,
        movement_id=movement_id,
    )
    return LedgerMovementResponse(
        public_id=reversal.id,
        movement_type=reversal.movement_type,
        amount=reversal.amount,
        balance_after=reversal.balance_after,
        appointment_id=reversal.appointment_id,
        notes=reversal.notes,
        created_at=reversal.created_at,
    )
