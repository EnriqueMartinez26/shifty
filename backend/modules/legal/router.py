"""Textos legales: versiones vigentes (publico) y aceptacion B2B de la tienda.

- ``GET /public/legal/versions``: anonimo, sin datos de ninguna tienda; lo
  lee el portal antes de mostrar la casilla de aceptacion.
- ``GET /public/unsubscribe`` (``token`` en la query) y
  ``POST /public/unsubscribe`` (``{token}``, para la pagina del front): baja del mail promocional por el link
  firmado del mail; anonimo, rate limit ``public-read``.
- ``POST /stores/me/terms-acceptance``: el admin de la tienda acepta la
  version vigente de los terminos B2B. Solo el admin de la tienda: el soporte
  global no acepta un contrato en nombre de la tienda.
- ``GET /stores/me/terms-acceptance``: la ultima aceptacion y si cubre la
  version vigente (admins, soporte global incluido).

El router del panel lleva la guarda de suspension (``main.py``); aceptar
esta en ``SUSPENSION_ALLOWED_WRITES``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.database import get_db, tenant_bypass
from core.exceptions import PermissionDeniedException
from core.rate_limit import client_ip_from_request, enforce_rate_limit
from core.roles import ROLE_STORE_ADMIN, STORE_MANAGERS, canonical_role, has_any_role
from core.router import CanonicalAPIRouter
from modules.auth.dependencies import get_current_user
from modules.legal.model import StoreTermsAcceptance
from modules.legal.schemas import (
    LegalVersionsResponse,
    StoreTermsAcceptanceResponse,
    StoreTermsStatusResponse,
    UnsubscribeRequest,
    UnsubscribeResponse,
)
from modules.legal.service import MarketingOptOutService, StoreTermsService
from modules.legal.versions import current_versions
from modules.users.model import User

public_router = CanonicalAPIRouter(prefix="/public", tags=["Public Legal"])
router = CanonicalAPIRouter(prefix="/stores/me/terms-acceptance", tags=["Store Terms"])


@public_router.get("/legal/versions", response_model=LegalVersionsResponse)
async def get_legal_versions() -> LegalVersionsResponse:
    """Versiones vigentes de los terminos y de la politica de privacidad. El
    portal las manda con la aceptacion (reserva y lista de espera)."""
    return LegalVersionsResponse(**current_versions())


@public_router.get("/unsubscribe", response_model=UnsubscribeResponse)
async def unsubscribe_from_marketing(
    request: Request,
    token: Annotated[str, Query(min_length=1, max_length=256)],
    db: AsyncSession = Depends(get_db),
) -> UnsubscribeResponse:
    """Baja del mail promocional "volve a reservar" por el link firmado del
    mail (art. 27 Ley 25.326). Confirmacion neutra e idempotente; un link
    adulterado o vencido es 400 ``UNSUBSCRIBE_LINK_INVALID``. El token no se
    loguea (el borde registra ``$uri`` sin query y Sentry la descarta)."""
    await enforce_rate_limit(
        request, "public:unsubscribe", settings.RATE_LIMIT_PUBLIC_READ_PER_MINUTE
    )
    async with tenant_bypass(db):
        await MarketingOptOutService(db).opt_out(token)
    return UnsubscribeResponse(status="unsubscribed")


@public_router.post("/unsubscribe", response_model=UnsubscribeResponse)
async def unsubscribe_from_marketing_post(
    request: Request,
    data: UnsubscribeRequest,
    db: AsyncSession = Depends(get_db),
) -> UnsubscribeResponse:
    """Misma baja que el GET, con el token en el cuerpo. La usa la pagina de
    confirmacion del front: los escaneres de correo abren los links GET del
    mail y darian de baja sin que la persona lo pidiera (revision de
    fix/legal-datos, 2026-09-25). El GET sigue mientras el link del mail
    apunte a la API."""
    await enforce_rate_limit(
        request, "public:unsubscribe", settings.RATE_LIMIT_PUBLIC_READ_PER_MINUTE
    )
    async with tenant_bypass(db):
        await MarketingOptOutService(db).opt_out(data.token)
    return UnsubscribeResponse(status="unsubscribed")


def _to_response(acceptance: StoreTermsAcceptance) -> StoreTermsAcceptanceResponse:
    return StoreTermsAcceptanceResponse(
        terms_version=acceptance.terms_version,
        accepted_at=acceptance.accepted_at,
        accepted_by=acceptance.user_id,
    )


@router.post(
    "",
    response_model=StoreTermsAcceptanceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def accept_store_terms(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StoreTermsAcceptanceResponse:
    """El admin de la tienda acepta la version vigente (``STORE_TERMS_VERSION``)."""
    if canonical_role(user) != ROLE_STORE_ADMIN:
        raise PermissionDeniedException("aceptar los terminos de la tienda")
    acceptance = await StoreTermsService(db).accept(
        actor=user, client_ip=client_ip_from_request(request)
    )
    return _to_response(acceptance)


@router.get("", response_model=StoreTermsStatusResponse)
async def get_store_terms_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StoreTermsStatusResponse:
    """Ultima aceptacion de la tienda y si cubre la version vigente. No
    bloquea nada: el front decide que hacer si falta."""
    if not has_any_role(user, STORE_MANAGERS):
        raise PermissionDeniedException("ver la aceptacion de los terminos")
    estado = await StoreTermsService(db).status(user.store_id)
    return StoreTermsStatusResponse(
        current_version=estado.current_version,
        current_version_accepted=estado.current_version_accepted,
        latest=_to_response(estado.latest) if estado.latest else None,
    )
