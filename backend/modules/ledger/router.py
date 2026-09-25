from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal
from collections.abc import Sequence
from typing import Annotated, Any

from fastapi import Depends, Path, Query
from core.router import CanonicalAPIRouter
from sqlalchemy import Row, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.exceptions import (
    FeatureDisabledException,
    PermissionDeniedException,
    StoreNotFoundException,
    ValidationException,
)
from core.feature_flags import is_store_feature_enabled
from core.keyset import (
    CURSOR_MAX_LENGTH,
    InvalidCursorError,
    before_key,
    decode_cursor,
    encode_cursor,
)
from core.validation import PUBLIC_ID_PATTERN, reject_control_chars
from core.roles import STORE_MANAGERS, has_any_role
from modules.auth.dependencies import get_current_user
from modules.ledger.model import CustomerLedger
from modules.ledger.schemas import (
    CustomerLedgerResponse,
    LedgerClientItem,
    LedgerMovementCreate,
    LedgerMovementResponse,
    LedgerSummaryClientItem,
    LedgerSummaryResponse,
)
from modules.ledger.service import (
    add_movement,
    current_balance,
    ensure_store_client,
    reverse_movement,
    search_store_clients,
)
from modules.otp.service import mask_phone
from modules.stores.model import Store
from modules.users.model import User, UserRole

router = CanonicalAPIRouter(prefix="/ledger", tags=["Customer Ledger"])
# Tope del historial de un cliente (AUD2-B2-10). Antes no habia ninguno.
LEDGER_PAGE_MAX = 200
LEDGER_PAGE_DEFAULT = 50
# Cota superior del salto: regla 9 exige ge Y le en todo parametro numerico.
LEDGER_OFFSET_MAX = 100_000
# Buscador de clientes del fiado (D3): una pagina corta alcanza para elegir.
LEDGER_CLIENTS_MAX = 100
LEDGER_CLIENTS_DEFAULT = 50
PublicIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]


def _require_financial_access(user: User) -> None:
    if user.role not in (UserRole.ADMIN, UserRole.STAFF) and not user.is_global_admin:
        raise PermissionDeniedException("ver deudas")


async def _ensure_ledger_feature_enabled(db: AsyncSession, user: User) -> None:
    # Solo la columna que decide (F3-01): la guarda corre en cada request del
    # fiado y no necesita la fila entera de la tienda.
    result = await db.execute(
        select(Store.feature_flags).where(Store.id == user.store_id)
    )
    row = result.one_or_none()
    if row is None:
        raise StoreNotFoundException(user.store_id)
    if not is_store_feature_enabled(row.feature_flags, "ledger"):
        raise FeatureDisabledException("deuda")


def _ledger_key(after: str | None, offset: int) -> tuple[datetime, str] | None:
    """Clave ``(created_at, id)`` del cursor ``after``; 422 si no es valido o
    si viene junto con un ``offset`` (dos formas de decir donde empieza)."""
    if after is None:
        return None
    if offset:
        raise ValidationException("after y offset no se combinan")
    try:
        return decode_cursor(after)
    except InvalidCursorError:
        raise ValidationException("Cursor de paginacion invalido") from None


# L3-03 (2026-09-25): el profesional ve el telefono del cliente enmascarado
# y no ve su email, como en la agenda, la busqueda y la lista de espera
# (``show_phone``). El profesional busca solo por nombre: ampliando ``q`` de a
# un digito reconstruia el numero enmascarado (decision de Mateo, revision de
# fix/legal-datos, 2026-09-25). El admin sigue buscando por telefono.
VISIBLE_PHONE_DIGITS = 3


def _shows_contact(user: User) -> bool:
    return has_any_role(user, STORE_MANAGERS)


def _client_phone(client: User, *, full_contact: bool) -> str | None:
    if not client.phone or full_contact:
        return client.phone
    return mask_phone(client.phone, visible=VISIBLE_PHONE_DIGITS)


def _client_display_name(
    user: User | None, *, fallback_id: str, full_contact: bool
) -> str:
    """Nombre del cliente; sin nombre cae al email o al telefono completos
    solo para un admin. Para el resto, al telefono enmascarado o al id."""
    if user:
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        if full_name:
            return full_name
        if full_contact and user.email:
            return user.email
        if user.phone:
            return _client_phone(user, full_contact=full_contact) or fallback_id
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
        top_debtors=_top_debtor_items(top_result.all(), viewer=user),
    )


def _top_debtor_items(
    rows: Sequence[Row[Any]], *, viewer: User
) -> list[LedgerSummaryClientItem]:
    """Filas del top de deudores con el nombre visible para ``viewer``
    (L3-03: sin nombre, el profesional no ve el email ni el telefono
    completos). Extraido de ``get_ledger_summary`` por la regla 29."""
    full_contact = _shows_contact(viewer)
    return [
        LedgerSummaryClientItem(
            client_id=client_id,
            client_name=_client_display_name(
                customer, fallback_id=client_id, full_contact=full_contact
            ),
            balance=Decimal(str(balance_after)).quantize(Decimal("0.01")),
            last_movement_at=created_at,
        )
        for client_id, balance_after, created_at, customer in rows
    ]


@router.get(
    "/clients",
    response_model=list[LedgerClientItem],
    summary="Buscador de clientes del fiado",
    description=(
        "Clientes activos de la tienda para elegir a quien cargar fiado. Solo "
        "cuentas con rol cliente: el rol lo fija el servidor. `q` (2..80): "
        "nombre que contiene q o digitos del telefono, como `GET /users/?q=`; "
        "para el profesional, solo nombre. El admin recibe email y telefono "
        "completos; el profesional, el telefono enmascarado (`***` y los "
        "ultimos 3 digitos) y `email` null."
    ),
)
async def search_ledger_clients(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    q: Annotated[str | None, Query(min_length=2, max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=LEDGER_CLIENTS_MAX)] = LEDGER_CLIENTS_DEFAULT,
) -> list[LedgerClientItem]:
    """Decision de Mateo (2026-09-25, D3): el profesional busca clientes para
    el fiado sin ``/users/``, que es del admin y lista tambien al personal.
    Misma puerta que el resto del fiado (rol, modulo, suspension por router)."""
    _require_financial_access(user)
    try:
        reject_control_chars(q)
    except ValueError as exc:
        raise ValidationException(str(exc)) from None
    await _ensure_ledger_feature_enabled(db, user)
    full_contact = _shows_contact(user)
    # Solo el admin busca por digitos del telefono (ver VISIBLE_PHONE_DIGITS).
    clientes = await search_store_clients(
        db, store_id=user.store_id, q=q, limit=limit, by_phone=full_contact
    )
    return [
        LedgerClientItem(
            public_id=cliente.public_id,
            name=_client_display_name(
                cliente, fallback_id=cliente.public_id, full_contact=full_contact
            ),
            email=cliente.email if full_contact else None,
            phone=_client_phone(cliente, full_contact=full_contact),
        )
        for cliente in clientes
    ]


@router.get(
    "/customers/{client_id}",
    response_model=CustomerLedgerResponse,
    summary="Historial de fiado de un cliente (paginado)",
    description=(
        "Devuelve una pagina del historial, del movimiento mas nuevo al mas "
        "viejo, mas el saldo vigente y el total de movimientos. El saldo NO "
        "depende de la pagina: sale del ultimo movimiento del cliente."
    ),
)
async def get_customer_ledger(
    client_id: PublicIdPath,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: Annotated[int, Query(ge=1, le=LEDGER_PAGE_MAX)] = LEDGER_PAGE_DEFAULT,
    offset: Annotated[int, Query(ge=0, le=LEDGER_OFFSET_MAX)] = 0,
    # F3-08 (aditivo): `next_cursor` de la pagina anterior; reemplaza a `offset`.
    after: Annotated[str | None, Query(max_length=CURSOR_MAX_LENGTH)] = None,
) -> CustomerLedgerResponse:
    # Autorizacion antes que el cursor: sin acceso es 403, no 422.
    _require_financial_access(user)
    clave = _ledger_key(after, offset)
    await _ensure_ledger_feature_enabled(db, user)
    # SEG-01: un cliente de otra tienda (o inexistente) es 404, como en el
    # alta (B2-11), no un historial vacio con saldo 0.
    await ensure_store_client(db, store_id=user.store_id, client_id=client_id)
    del_cliente = (
        CustomerLedger.store_id == user.store_id,
        CustomerLedger.client_id == client_id,
    )
    pagina = (
        select(CustomerLedger)
        .where(*del_cliente)
        # Mas nuevo primero: con un tope, la pagina util es la reciente.
        # El id desempata para que dos filas del mismo instante no se
        # repitan ni se salteen entre paginas.
        .order_by(CustomerLedger.created_at.desc(), CustomerLedger.id.desc())
    )
    if clave is not None:
        pagina = pagina.where(
            before_key(CustomerLedger.created_at, CustomerLedger.id, *clave)
        )
    # Una fila de mas dice si hay pagina siguiente sin otra consulta.
    result = await db.execute(pagina.limit(limit + 1).offset(offset))
    movements = list(result.scalars().all())
    has_more = len(movements) > limit
    movements = movements[:limit]
    # El saldo y el total salen de SQL (regla 11): antes el saldo era
    # ``movements[-1].balance_after``, que obligaba a traer el historial
    # entero para leer un solo numero (AUD2-B2-10).
    balance = await current_balance(db, user.store_id, client_id)
    total = (
        await db.execute(
            select(func.count()).select_from(CustomerLedger).where(*del_cliente)
        )
    ).scalar_one()
    return CustomerLedgerResponse(
        client_id=client_id,
        balance=balance,
        total=int(total or 0),
        next_cursor=(
            encode_cursor(movements[-1].created_at, movements[-1].id)
            if has_more
            else None
        ),
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
