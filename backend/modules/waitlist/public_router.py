"""Lista de espera desde la pagina publica de la tienda.

Anotarse no pide OTP (rate limit por telefono, como el resto de las escrituras
publicas): la friccion mataria la lista. Ver o borrar la propia entrada si
exige el OTP reciente, igual que "mis turnos".
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Path, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import _apply_tenant_context, get_db, set_tenant_context
from core.exceptions import ResourceNotFoundException, StoreNotFoundException
from core.rate_limit import enforce_rate_limit
from core.router import CanonicalAPIRouter
from core.validation import PUBLIC_ID_PATTERN
from modules.public_api.repository import PublicRepository
from modules.public_api.router import _require_recent_client_otp
from modules.stores.model import Store
from modules.waitlist.schemas import (
    WaitlistClientQuery,
    WaitlistEntryResponse,
    WaitlistJoinRequest,
)
from modules.waitlist.service import WaitlistService, to_row_dict

router = CanonicalAPIRouter(prefix="/public/waitlist", tags=["Public Waitlist"])
EntryIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]


async def _store(db: AsyncSession, store_public_id: str) -> Store:
    # Endpoint anonimo: sin tenant en el request, el contexto global es lo
    # que permite leer la tienda (mismo patron que el resto de /public).
    set_tenant_context(None, is_admin=True)
    await _apply_tenant_context(db)
    store = await PublicRepository(db).get_store_by_public_id(store_public_id)
    if not store:
        raise StoreNotFoundException(identifier=store_public_id)
    return store


@router.post(
    "", response_model=WaitlistEntryResponse, status_code=status.HTTP_201_CREATED
)
async def join_waitlist(
    request: Request,
    data: WaitlistJoinRequest,
    db: AsyncSession = Depends(get_db),
) -> WaitlistEntryResponse:
    await enforce_rate_limit(
        request,
        "public:waitlist:join",
        settings.RATE_LIMIT_PUBLIC_WRITE_PER_MINUTE,
        subject=data.client_phone,
    )
    try:
        store = await _store(db, data.store_public_id)
        row = await WaitlistService(db).join(
            store=store,
            service_public_id=data.service_id,
            staff_public_id=data.staff_id,
            window_starts_at=data.window_starts_at,
            window_ends_at=data.window_ends_at,
            client_name=data.client_name,
            client_phone=data.client_phone,
            client_email=str(data.client_email) if data.client_email else None,
            notes=data.notes,
        )
        return WaitlistEntryResponse(**to_row_dict(row, show_contact=True))
    finally:
        set_tenant_context(None, False)


@router.post("/mine", response_model=list[WaitlistEntryResponse])
async def my_waitlist_entries(
    request: Request,
    data: WaitlistClientQuery,
    db: AsyncSession = Depends(get_db),
) -> list[WaitlistEntryResponse]:
    await enforce_rate_limit(
        request,
        "public:waitlist:mine",
        settings.RATE_LIMIT_PUBLIC_READ_PER_MINUTE,
        subject=data.phone,
    )
    try:
        store = await _store(db, data.store_public_id)
        await _require_recent_client_otp(db, store_id=store.id, phone=data.phone)
        rows = await WaitlistService(db).list_for_client(store.id, data.phone)
        return [
            WaitlistEntryResponse(**to_row_dict(r, show_contact=True)) for r in rows
        ]
    finally:
        set_tenant_context(None, False)


@router.post("/{entry_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_waitlist(
    entry_id: EntryIdPath,
    request: Request,
    data: WaitlistClientQuery,
    db: AsyncSession = Depends(get_db),
) -> None:
    await enforce_rate_limit(
        request,
        "public:waitlist:leave",
        settings.RATE_LIMIT_PUBLIC_WRITE_PER_MINUTE,
        subject=data.phone,
    )
    try:
        store = await _store(db, data.store_public_id)
        await _require_recent_client_otp(db, store_id=store.id, phone=data.phone)
        svc = WaitlistService(db)
        entry = await svc.get_open(store.id, entry_id)
        if entry.client_phone != data.phone:
            # Misma respuesta que "no existe": no se confirma la entrada ajena.
            raise ResourceNotFoundException("Entrada de lista de espera", entry_id)
        await svc.cancel(entry)
    finally:
        set_tenant_context(None, False)
