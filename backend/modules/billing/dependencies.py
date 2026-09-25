"""Guarda de suscripcion suspendida.

Decision de producto (2026-09-10): una tienda suspendida deja de aparecer en
la vitrina publica y no puede escribir desde el panel; el login y la lectura
siguen para que el dueno vea el aviso y pueda pagar. El superadmin no queda
atrapado por la guarda: es quien reactiva la tienda.

Se aplica a nivel router (``dependencies=[Depends(block_writes_when_suspended)]``)
para que un endpoint de escritura nuevo quede cubierto sin acordarse de nada.

Decision (2026-09-19, OK global del usuario, sugerencia del brief; audit
B7-02 con B4-03, B5-14 y B1-06): se permite el housekeeping y se bloquea todo
lo que genera una obligacion nueva. La regla es explicita por endpoint y
verbo (``SUSPENSION_ALLOWED_WRITES``), no "todo POST": una escritura nueva
nace bloqueada y permitirla es agregarla a esa tabla con su motivo. El portal
publico no tiene usuario: ahi la regla vive en los dos handlers que crean
obligaciones (``reject_new_public_business_when_suspended``).
"""

from __future__ import annotations

from http import HTTPStatus

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.exceptions import AppException, StoreNotFoundException
from modules.auth.dependencies import get_optional_current_user
from modules.billing.service import store_is_suspended
from modules.stores.model import Store
from modules.users.model import User

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Escrituras del panel que una tienda suspendida SIGUE pudiendo hacer:
# ``(verbo, plantilla de ruta)`` tal como la registra FastAPI. Todas son
# housekeeping, ninguna genera una obligacion nueva.
SUSPENSION_ALLOWED_WRITES: frozenset[tuple[str, str]] = frozenset(
    {
        # B4-03: marcar leido no es escritura a los fines de la suspension; el
        # panel lo hace solo al abrir el aviso que le dice que pague.
        ("POST", "/notifications/{notification_id}/read"),
        ("POST", "/notifications/read-all"),
        # B5-14: exportar lo propio es una lectura con verbo POST.
        ("POST", "/reports/export"),
        # Baja de un usuario: cortar el acceso de un ex empleado no puede
        # esperar a que la tienda pague. El alta y la edicion (que puede
        # reactivarlo o subirle el rol) si quedan bloqueadas. Criterio del
        # coordinador, pendiente de confirmacion del usuario.
        ("DELETE", "/users/{public_id}"),
        # Pagos: cobrar turnos ya tomados y operar la pasarela no generan una
        # obligacion nueva para la tienda. El router de pagos lleva la guarda
        # igual: un endpoint de pagos nuevo nace bloqueado hasta que se lo
        # agregue aca con su motivo. El webhook de Mercado Pago pasa porque es
        # anonimo (la guarda solo mira usuarios con tienda). Los movimientos de
        # ledger (cargar y revertir) NO estan: revertir un pago le vuelve a
        # crear deuda al cliente.
        # Configurar y desconectar la pasarela (la tienda tiene que poder
        # arreglar o cortar su cuenta de cobro mientras regulariza).
        ("PUT", "/payments/gateway-config"),
        ("POST", "/payments/mercadopago/oauth/start"),
        ("POST", "/payments/mercadopago/oauth/refresh"),
        ("DELETE", "/payments/mercadopago/oauth/connection"),
        # Link de pago de un turno ya tomado: cobra lo que ya se debe.
        ("POST", "/payments/preferences/{appointment_id}"),
        # Confirmar a mano un pago recibido y devolverlo: cierran cobros de
        # turnos existentes.
        ("POST", "/payments/{appointment_id}/manual-confirm"),
        ("POST", "/payments/{payment_id}/refund"),
        # Procesar la cola de efectos de pagos ya ocurridos.
        ("POST", "/payments/outbox/process"),
        # Aceptar los terminos B2B (L1, 2026-09-25): no genera una obligacion
        # nueva y la tienda tiene que poder aceptarlos mientras regulariza.
        ("POST", "/stores/me/terms-acceptance"),
        # Anonimizar un cliente (PV-05, 2026-09-25): atender un pedido de
        # supresion es una obligacion legal con plazo (art. 16 Ley 25.326) y
        # no crea una obligacion comercial nueva.
        ("POST", "/users/{client_id}/anonymize"),
    }
)


class SubscriptionSuspendedException(AppException):
    def __init__(self) -> None:
        super().__init__(
            message=(
                "Tu suscripcion esta suspendida: renovala para volver a operar. "
                "Podes seguir viendo tu informacion mientras tanto."
            ),
            http_status=HTTPStatus.PAYMENT_REQUIRED,
            error_code="SUBSCRIPTION_SUSPENDED",
        )


async def block_writes_when_suspended(
    request: Request,
    user: User | None = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    # Usuario OPCIONAL: estos routers tienen GET publicos (por ejemplo, servir
    # el logo de la tienda). Exigir autenticacion aca los rompia con 401.
    if request.method in SAFE_METHODS:
        return
    route = request.scope.get("route")
    template = getattr(route, "path", request.url.path)
    if (request.method, template) in SUSPENSION_ALLOWED_WRITES:
        return
    if user is None or user.is_global_admin or not user.store_id:
        return
    if await store_is_suspended(db, user.store_id):
        raise SubscriptionSuspendedException()


async def reject_new_public_business_when_suspended(
    db: AsyncSession, store: Store
) -> None:
    """Portal publico (B1-06): una tienda suspendida no toma obligaciones nuevas.

    Se llama SOLO desde crear una reserva y anotarse en la lista de espera.
    Cancelar y reprogramar un turno ya tomado siguen: no se castiga al cliente
    por la mora de la tienda. Responde el mismo 404 que la vitrina publica,
    sin revelar el motivo.
    """
    if await store_is_suspended(db, store.id):
        raise StoreNotFoundException(identifier=store.public_id)
