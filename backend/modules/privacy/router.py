"""Derechos del titular: exportar y anonimizar a un cliente (PV-05, L3-06).

Rutas bajo ``/users/{client_id}/...`` en un router propio para no tocar
``modules/users/router.py``. Solo admins de la tienda (``get_current_admin``:
admin de tienda y soporte global, acotados a la tienda del usuario). Lleva la
guarda de suspension (``main.py``); anonimizar esta permitido con la tienda
suspendida (``SUSPENSION_ALLOWED_WRITES``): es una obligacion legal, no una
obligacion comercial nueva. El procedimiento manual esta en
``docs/DERECHOS_DE_LOS_TITULARES.md``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Path
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.router import CanonicalAPIRouter
from core.validation import PUBLIC_ID_PATTERN
from modules.auth.dependencies import get_current_admin
from modules.privacy.schemas import AnonymizeResponse, ClientDataExport
from modules.privacy.service import DataSubjectService
from modules.users.model import User

router = CanonicalAPIRouter(prefix="/users", tags=["Data Subject Rights"])
ClientIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]


@router.get("/{client_id}/export", response_model=ClientDataExport)
async def export_client_data(
    client_id: ClientIdPath,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> ClientDataExport:
    """Datos personales del cliente y sus turnos, cobros, fiado y lista de
    espera de ESTA tienda (derecho de acceso). 404 si no es un cliente de la
    tienda."""
    return await DataSubjectService(db).export(client_id=client_id, actor=admin)


@router.post("/{client_id}/anonymize", response_model=AnonymizeResponse)
async def anonymize_client(
    client_id: ClientIdPath,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
) -> AnonymizeResponse:
    """Supresion: reemplaza los datos personales del cliente por valores
    neutros y lo deja inactivo; conserva importes, fechas y estados. 409
    ``CLIENT_HAS_LIVE_CHARGE`` / ``CLIENT_HAS_ACTIVE_APPOINTMENTS`` /
    ``CLIENT_HAS_DEBT`` si tiene un cobro abierto, turnos activos a futuro o
    saldo en el fiado; 404 si no es un cliente de la tienda. No se puede
    deshacer."""
    await DataSubjectService(db).anonymize(client_id=client_id, actor=admin)
    return AnonymizeResponse(status="anonymized")
