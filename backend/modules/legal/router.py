"""Textos legales: versiones vigentes (publico) y aceptacion B2B de la tienda.

- ``GET /public/legal/versions``: anonimo, sin datos de ninguna tienda; lo
  lee el portal antes de mostrar la casilla de aceptacion.
- ``POST /stores/me/terms-acceptance``: el admin de la tienda acepta la
  version vigente de los terminos B2B. Solo el admin de la tienda: el soporte
  global no acepta un contrato en nombre de la tienda.
- ``GET /stores/me/terms-acceptance``: la ultima aceptacion y si cubre la
  version vigente (admins, soporte global incluido).

El router del panel lleva la guarda de suspension (``main.py``); aceptar
esta en ``SUSPENSION_ALLOWED_WRITES``.
"""

from __future__ import annotations

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.exceptions import PermissionDeniedException
from core.rate_limit import client_ip_from_request
from core.roles import ROLE_STORE_ADMIN, STORE_MANAGERS, canonical_role, has_any_role
from core.router import CanonicalAPIRouter
from modules.auth.dependencies import get_current_user
from modules.legal.model import StoreTermsAcceptance
from modules.legal.schemas import (
    LegalVersionsResponse,
    StoreTermsAcceptanceResponse,
    StoreTermsStatusResponse,
)
from modules.legal.service import StoreTermsService
from modules.legal.versions import current_versions
from modules.users.model import User

public_router = CanonicalAPIRouter(prefix="/public/legal", tags=["Public Legal"])
router = CanonicalAPIRouter(prefix="/stores/me/terms-acceptance", tags=["Store Terms"])


@public_router.get("/versions", response_model=LegalVersionsResponse)
async def get_legal_versions() -> LegalVersionsResponse:
    """Versiones vigentes de los terminos y de la politica de privacidad. El
    portal las manda con la aceptacion (reserva y lista de espera)."""
    return LegalVersionsResponse(**current_versions())


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
