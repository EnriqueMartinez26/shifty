"""Capa de servicio del fiado: dueña de la transaccion y del saldo incremental.

``balance_after`` es un saldo que se arrastra (se lee el ultimo movimiento y se
le suma el nuevo), asi que el lock que lo serializa y el commit que lo
persiste son la misma unidad de trabajo. Vivian en el router
(``ledger/router.py``), donde no se podian ejercer sin HTTP; desde B2-09 el
router solo autoriza, carga y responde (CLAUDE.md §2).
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import ResourceNotFoundException, ValidationException
from modules.ledger.model import CustomerLedger


async def _lock_client_ledger(db: AsyncSession, store_id: str, client_id: str) -> None:
    """Serializa los movimientos de un mismo cliente.

    balance_after es un saldo incremental: se lee el ultimo y se le suma el
    movimiento nuevo. Sin serializar, dos movimientos concurrentes leen el mismo
    saldo previo y el segundo pisa al primero, corrompiendo la cuenta. Un
    advisory lock por (tienda, cliente) los ordena; se libera al cerrar la
    transaccion. En SQLite (tests) es no-op: no hay concurrencia real ahi.
    """
    if db.bind and db.bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtext(:clave))"),
            {"clave": f"ledger:{store_id}:{client_id}"},
        )


async def _previous_balance(db: AsyncSession, store_id: str, client_id: str) -> Decimal:
    """Ultimo saldo del cliente (0 si no tiene movimientos). Con el lock tomado."""
    result = await db.execute(
        select(CustomerLedger)
        .where(
            CustomerLedger.store_id == store_id,
            CustomerLedger.client_id == client_id,
        )
        .order_by(CustomerLedger.created_at.desc())
        .limit(1)
    )
    previous = result.scalar_one_or_none()
    return previous.balance_after if previous else Decimal("0.00")


async def add_movement(
    db: AsyncSession,
    *,
    store_id: str,
    client_id: str,
    movement_type: str,
    amount: Decimal,
    appointment_id: str | None = None,
    notes: str | None = None,
) -> CustomerLedger:
    """Carga un movimiento y devuelve el saldo resultante, ya commiteado."""
    # Lock por cliente antes de leer el saldo previo: evita que dos movimientos
    # concurrentes calculen balance_after sobre el mismo saldo y se pisen.
    await _lock_client_ledger(db, store_id, client_id)
    previous_balance = await _previous_balance(db, store_id, client_id)
    movement = CustomerLedger(
        store_id=store_id,
        client_id=client_id,
        appointment_id=appointment_id,
        movement_type=movement_type,
        amount=amount,
        # El signo lo decide la entidad.
        balance_after=previous_balance + CustomerLedger.signed(movement_type, amount),
        notes=notes,
    )
    db.add(movement)
    await db.commit()
    await db.refresh(movement)
    return movement


async def reverse_movement(
    db: AsyncSession, *, store_id: str, client_id: str, movement_id: str
) -> CustomerLedger:
    """Anula un movimiento cargado por error.

    No borra el original (rompe la trazabilidad del saldo): agrega un
    movimiento de ajuste que compensa su efecto y deja el saldo como si el
    movimiento erroneo nunca hubiera existido. Cada movimiento se puede
    revertir una sola vez.
    """
    await _lock_client_ledger(db, store_id, client_id)

    original = (
        await db.execute(
            select(CustomerLedger).where(
                CustomerLedger.id == movement_id,
                CustomerLedger.store_id == store_id,
                CustomerLedger.client_id == client_id,
            )
        )
    ).scalar_one_or_none()
    if original is None:
        raise ResourceNotFoundException("Movimiento de fiado", movement_id)

    if original.is_reversal:
        raise ValidationException(
            "Un movimiento de reversa no se puede volver a revertir."
        )

    already = (
        await db.execute(
            select(CustomerLedger.id).where(
                CustomerLedger.reverses_id == original.id,
                CustomerLedger.store_id == store_id,
            )
        )
    ).scalar_one_or_none()
    if already is not None:
        raise ValidationException("Ese movimiento ya fue revertido.")

    # La entidad decide como se compensa (ajuste con signo opuesto) y marca el
    # candado reverses_id; aca solo calculamos el saldo resultante y persistimos.
    previous_balance = await _previous_balance(db, store_id, client_id)
    reversal = original.build_reversal(
        balance_after=previous_balance - original.signed_amount
    )
    db.add(reversal)
    await db.commit()
    await db.refresh(reversal)
    return reversal
