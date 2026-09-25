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
from modules.appointments.model import Appointment
from modules.ledger.model import CustomerLedger
from modules.users.model import User, UserRole
from modules.users.repository import UserRepository


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


async def current_balance(db: AsyncSession, store_id: str, client_id: str) -> Decimal:
    """Ultimo saldo del cliente (0 si no tiene movimientos).

    Una sola fila: el saldo es un dato, no el resultado de traer el historial
    a memoria (regla 11). ``add_movement`` la llama CON el lock tomado; el
    endpoint de lectura la llama sin lock, que es lo que corresponde a una
    consulta (AUD2-B2-10).
    """
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


async def ensure_store_client(
    db: AsyncSession, *, store_id: str, client_id: str
) -> None:
    """El movimiento se carga contra un usuario de ESTA tienda, o no se carga.

    2026-09-17, hallazgo B2-11: el alta aceptaba cualquier id que matcheara
    PUBLIC_ID_PATTERN y lo persistia, asi que una fila de fiado podia quedar
    apuntando al usuario de otra tienda. En Postgres la RLS de `users` lo
    tapa, pero la suite corre en SQLite (CLAUDE.md §4) y §2 exige el filtro
    `store_id` como defensa en profundidad junto a la RLS, no en su lugar. Un
    id inexistente pasa de 409 generico (por FK) a 404 explicito.

    2026-09-24, SEG-01: el historial (``GET /ledger/customers/{client_id}``)
    usa el mismo chequeo; antes devolvia 200 con saldo 0 para un cliente
    ajeno.
    """
    cliente = await UserRepository(db).get_by_public_id(client_id, store_id)
    if cliente is None:
        raise ResourceNotFoundException("Cliente", client_id)


async def search_store_clients(
    db: AsyncSession, *, store_id: str, q: str | None, limit: int
) -> list[User]:
    """Clientes activos de ESTA tienda para el buscador del fiado (D3).

    El rol ``client`` y la tienda los fija el servidor: el profesional usa el
    fiado pero no ``/users/`` (regla 16), asi que ninguna cuenta del personal,
    de un admin ni del soporte global sale por aca, pida lo que pida el
    query. Misma busqueda que ``GET /users/?q=`` (``user_search_condition``,
    acotada por ``ix_users_store_id``).
    """
    return await UserRepository(db).get_all(
        store_id,
        only_active=True,
        role=UserRole.CLIENT.value,
        q=q,
        limit=limit,
        include_global_admins=False,
    )


async def _ensure_store_appointment(
    db: AsyncSession, *, store_id: str, appointment_id: str
) -> None:
    """El turno asociado al movimiento es de ESTA tienda, o el movimiento no se carga.

    2026-09-20, hallazgo AUD2-B2-16: B2-11 cerro la mitad del hueco (el
    cliente) y dejo el ``appointment_id`` sin comprobar. La FK a
    ``appointments.id`` no pasa por RLS (Postgres verifica restricciones por
    fuera de las politicas), asi que una fila de fiado podia quedar apuntando
    al turno de otra tienda. Mismo criterio que ``ensure_store_client``:
    filtro ``store_id`` como defensa en profundidad (CLAUDE.md §2), y un id
    inexistente pasa de 409 generico (por FK) a 404 explicito.
    """
    turno = await db.scalar(
        select(Appointment.id).where(
            Appointment.id == appointment_id,
            Appointment.store_id == store_id,
        )
    )
    if turno is None:
        raise ResourceNotFoundException("Turno", appointment_id)


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
    await ensure_store_client(db, store_id=store_id, client_id=client_id)
    if appointment_id is not None:
        await _ensure_store_appointment(
            db, store_id=store_id, appointment_id=appointment_id
        )
    # Lock por cliente antes de leer el saldo previo: evita que dos movimientos
    # concurrentes calculen balance_after sobre el mismo saldo y se pisen.
    await _lock_client_ledger(db, store_id, client_id)
    previous_balance = await current_balance(db, store_id, client_id)
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
    previous_balance = await current_balance(db, store_id, client_id)
    reversal = original.build_reversal(
        balance_after=previous_balance - original.signed_amount
    )
    db.add(reversal)
    await db.commit()
    await db.refresh(reversal)
    return reversal
