from fastapi import FastAPI, Depends, Request
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import structlog
from core.config import settings
from core.database import engine
from core.middleware import TenantMiddleware
from core.runtime_contracts import ensure_runtime_contracts
from core.exceptions import AppException
from core.rate_limit import RedisRateLimitMiddleware
from core.security_middleware import RequestGuardMiddleware, SecurityHeadersMiddleware
from modules.appointment_blocks.router import router as appointment_blocks_router
from modules.auth.router import router as auth_router
from modules.services.router import router as services_router
from modules.staff.router import router as staff_router
from modules.appointments.router import router as appointments_router
from modules.dashboard.router import router as dashboard_router
from modules.auth.dependencies import get_current_user
from modules.users.model import User
from modules.users.router import router as users_router
from modules.public.router import router as public_router
from modules.reports.router import router as reports_router
from modules.budget.router import router as budget_router
from modules.ledger.router import router as ledger_router
from modules.ops.router import router as ops_router
from modules.payments.router import router as payments_router
from modules.promotions.router import router as promotions_router
from modules.stores.router import router as stores_router
from modules.superadmin.router import router as superadmin_router

logger = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.RUN_RUNTIME_CONTRACTS_ON_STARTUP:
        await ensure_runtime_contracts(engine)
    yield

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Sistema de gestión de turnos multi-tenant",
    lifespan=lifespan,
    docs_url="/docs" if settings.EXPOSE_API_DOCS else None,
    redoc_url="/redoc" if settings.EXPOSE_API_DOCS else None,
    openapi_url="/openapi.json" if settings.EXPOSE_API_DOCS else None,
)

from fastapi.exceptions import RequestValidationError

@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """
    Handler global: convierte cualquier AppException del dominio en una
    respuesta JSON estructurada con su HTTP status code correspondiente.
    """
    return JSONResponse(
        status_code=exc.http_status,
        content={
            "success": False,
            "error_code": exc.error_code,
            "message": exc.message,
            "detail": exc.detail,
        },
    )

from fastapi.encoders import jsonable_encoder

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """
    Handler para errores de validación de Pydantic (422).
    Normaliza la salida para que el frontend reciba SIEMPRE strings, nunca objetos crudos.
    """
    # Convertir cada error a un string legible (nunca devolver objetos Pydantic)
    error_strings: list[str] = []
    for error in exc.errors():
        loc = " -> ".join([str(x) for x in error["loc"] if x != "body"])
        msg = error["msg"]
        error_strings.append(f"{loc}: {msg}" if loc else msg)
    
    readable_msg = "; ".join(error_strings) or "Error de validación en los datos enviados."
    
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error_code": "VALIDATION_ERROR",
            "message": readable_msg,
            # detail es lista de strings — nunca objetos — para que React pueda renderizar
            "detail": error_strings,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled_exception",
        path=str(request.url.path),
        method=request.method,
        error_type=type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error_code": "INTERNAL_SERVER_ERROR",
            "message": "Error interno del servidor",
        },
        headers={"Cache-Control": "no-store"},
    )



# IMPORTANTE: En Starlette, los middlewares se ejecutan en orden INVERSO al de registro.
# El SecurityHeadersMiddleware queda como capa externa; CORS envuelve a los guards,
# y los guards cortan payload/rate limit antes de llegar al tenant y routers.

# 1. Registrar TenantMiddleware primero
app.add_middleware(TenantMiddleware)
app.add_middleware(RedisRateLimitMiddleware)
app.add_middleware(RequestGuardMiddleware)

# 2. Configurar CORS (debe ser el último en registrarse para ser la capa más externa)
# Obtenemos los orígenes de la configuración y nos aseguramos de que no haya espacios.
origins = [o.strip() for o in settings.CORS_ORIGINS.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Idempotency-Key", "Content-Disposition"],
    max_age=600,
)

app.add_middleware(SecurityHeadersMiddleware)

# 3. Registrar Routers
app.include_router(auth_router)
app.include_router(services_router)
app.include_router(staff_router)
app.include_router(appointments_router)
app.include_router(dashboard_router)
app.include_router(users_router)
app.include_router(reports_router)
app.include_router(budget_router)
app.include_router(stores_router)
app.include_router(appointment_blocks_router)
app.include_router(payments_router)
app.include_router(promotions_router)
app.include_router(ledger_router)
app.include_router(ops_router)
app.include_router(superadmin_router)
app.include_router(public_router)

@app.get("/")
async def root():
    return {
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "online"
    }

@app.get("/me", tags=["Users"])
async def get_me(user: User = Depends(get_current_user)):
    """Ruta protegida para validar el token y el contexto del usuario."""
    return {
        "email": user.email,
        "role": user.role,
        "store_id": user.store_id,
        "public_id": user.public_id,
        "is_global_admin": user.is_global_admin,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
