from starlette.types import ASGIApp, Receive, Scope, Send
from core.database import set_tenant_context
from core.security import decode_token
from jose import JWTError
import structlog

logger = structlog.get_logger()

class TenantMiddleware:
    """
    Middleware ASGI puro que extrae el contexto del tenant del JWT 
    e inyecta la configuración en la base de datos (RLS) para el request actual.
    Evita conflictos con CORSMiddleware al no usar BaseHTTPMiddleware.
    """
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # 1. Obtener el token del Header
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("utf-8")
        
        # Seteamos contexto inicial
        set_tenant_context(None, False)
        
        if auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
            try:
                # 2. Decodificar Token
                payload = decode_token(token)
                store_id = payload.get("store_id")
                is_global_admin = payload.get("is_global_admin", False)
                
                # 3. Establecer Contexto
                set_tenant_context(store_id, is_global_admin)
                
                # Guardamos info en el scope para uso en dependencias
                if "state" not in scope:
                    scope["state"] = {}
                scope["state"]["user"] = payload
                
            except JWTError:
                pass
            except Exception as e:
                logger.error("error_injecting_tenant_context", error=str(e))

        try:
            await self.app(scope, receive, send)
        finally:
            # 4. Limpiar Contexto al terminar el request
            set_tenant_context(None, False)
