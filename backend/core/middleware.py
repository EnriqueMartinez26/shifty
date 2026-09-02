from starlette.types import ASGIApp, Receive, Scope, Send

from core.database import set_tenant_context


class TenantMiddleware:
    """Aísla el contexto de tenant entre requests.

    Antes este middleware decodificaba el JWT y seteaba el contexto RLS con los
    claims (``store_id`` / ``is_global_admin``). Eso convertía a un claim del
    token en la llave maestra de la base: un token viejo de superadmin seguía
    bypasseando RLS aunque el flag ya estuviera revocado en la DB, y un secreto
    filtrado permitía forjar el bypass.

    Ahora el contexto real lo establece ``get_current_user`` DESPUÉS de
    recargar al usuario desde la base (modules/auth/dependencies.py): la fuente
    de verdad es la DB, nunca el token. Acá solo se garantiza que cada request
    arranque y termine con el contexto limpio.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        set_tenant_context(None, False)
        try:
            await self.app(scope, receive, send)
        finally:
            set_tenant_context(None, False)
