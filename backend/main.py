from contextlib import asynccontextmanager
import json
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import structlog
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm.exc import StaleDataError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from core.config import SETTINGS_BOOT_ERROR, settings
from core.database import assert_rls_capable_role, engine
from core.middleware import TenantMiddleware
from core.logging import configure_logging
from core.observability import init_observability
from core.responses import CanonicalJsonMiddleware, error_response
from core.exceptions import AppException
from core.rate_limit import RedisRateLimitMiddleware
from core.redis import close_redis
from core.request_id import RequestIdMiddleware
from modules.payments.service import close_mercadopago_client
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

# NOTA: use public_api as the stable runtime import path for the public booking module.
from modules.public_api.router import router as public_router
from modules.reports.router import router as reports_router
from modules.ledger.router import router as ledger_router
from modules.ops.router import router as ops_router
from modules.notifications.router import router as notifications_router
from modules.payments.router import router as payments_router
from modules.promotions.router import router as promotions_router
from modules.stores.router import router as stores_router
from modules.superadmin.router import router as superadmin_router
from modules.billing.dependencies import block_writes_when_suspended
from modules.waitlist.public_router import router as public_waitlist_router
from modules.waitlist.router import router as waitlist_router

logger = structlog.get_logger()


class BootErrorMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or SETTINGS_BOOT_ERROR is None:
            await self.app(scope, receive, send)
            return

        if str(scope.get("method", "GET")).upper() == "OPTIONS":
            await self.app(scope, receive, send)
            return

        body = json.dumps(
            {
                "success": False,
                "error_code": "BACKEND_BOOT_FAILED",
                "message": "Backend configuration failed during startup.",
                "detail": SETTINGS_BOOT_ERROR,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        response_start: Message = {
            "type": "http.response.start",
            "status": 503,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode("ascii")),
                (b"cache-control", b"no-store"),
            ],
        }
        await send(
            {
                **response_start,
            }
        )
        await send({"type": "http.response.body", "body": body})


async def _assert_rls_capable_role() -> None:
    """Aborta el arranque si la app se conecta con un rol que saltea RLS.

    El cuerpo vive en ``core.database`` porque la API no es el unico proceso
    que se conecta: el worker y beat hacen el mismo chequeo en su arranque
    (AUD2-B7-08). Aca queda la lectura del engine del modulo, que es lo que los
    tests doblan.
    """
    await assert_rls_capable_role(engine)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        # Settings de respaldo: no hay base alcanzable y BootErrorMiddleware
        # responde 503 a toda request. Sin este corte el chequeo de RLS
        # fallaba contra localhost/invalid y el proceso moria antes de servir
        # el 503.
        if SETTINGS_BOOT_ERROR is not None:
            yield
            return
        await _assert_rls_capable_role()
        # Sin DDL en el arranque: el esquema lo crean las migraciones (regla
        # 13). El `create_all` + `ALTER TABLE` de runtime_contracts se borro
        # (B7-07/X-18, 2026-09-19).
        yield
    finally:
        await _close_redis_on_shutdown()
        await _close_mercadopago_client_on_shutdown()
        await _dispose_db_pool_on_shutdown()


async def _close_redis_on_shutdown() -> None:
    """Cierre ordenado del pool de Redis compartido (X-16, 2026-09-19).

    Sin esto las conexiones del pool quedaban abiertas del lado de Redis hasta
    su timeout en cada deploy o reinicio. Un Redis que ya no responde no puede
    trabar el apagado: se registra y se sigue.
    """
    try:
        await close_redis()
    except Exception:
        logger.warning("redis_close_failed_on_shutdown", exc_info=True)


async def _close_mercadopago_client_on_shutdown() -> None:
    """Cierra el cliente httpx compartido de Mercado Pago (F1-04, R11-20).

    Sus conexiones keep-alive quedaban abiertas hasta que el proceso moria.
    Best-effort como el de Redis: el apagado no se traba por esto.
    """
    try:
        await close_mercadopago_client()
    except Exception:
        logger.warning("mercadopago_client_close_failed_on_shutdown", exc_info=True)


async def _dispose_db_pool_on_shutdown() -> None:
    """Cierre ordenado del pool de Postgres (AUD2-B7-05, 2026-09-20).

    Mismo modo de fallo que X-16 declaro inaceptable para Redis, en el recurso
    que ademas ya se agoto una vez (regla 5, 2026-09-04): sin esto quedaban
    hasta DB_POOL_SIZE + DB_MAX_OVERFLOW conexiones abiertas contra Postgres
    por proceso de uvicorn tras cada apagado, hasta que las cerrara el timeout
    del servidor. Con `restart: always` y un contenedor de Postgres de 256M,
    un deploy con reinicios seguidos puede dejar la base sin cupo para el
    proceso nuevo.

    Va en su propio try y despues del cierre de Redis: una base que ya no
    responde no puede trabar el apagado, y un cierre no puede tapar al otro.
    """
    try:
        await engine.dispose()
    except Exception:
        logger.warning("db_pool_dispose_failed_on_shutdown", exc_info=True)


# Logs JSON (F0-22) antes que nada: lo que se loguee al arrancar ya sale con
# el formato de produccion. Sentry se inicializa antes de construir la app
# para que sus integraciones alcancen a instrumentar el ciclo de request.
configure_logging()
init_observability("api")

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Sistema de gestión de turnos multi-tenant",
    lifespan=lifespan,
    # Sin redirect por barra final: detras de nginx la app no conoce el
    # prefijo /api, asi que el 307 apuntaba a http://host/promotions/ (sin
    # /api), el navegador caia en el SPA y el front recibia HTML en vez de
    # JSON (crash de Promociones). Un mismatch ahora es un 404 visible en
    # tests y CI; tests/unit/test_frontend_routes_contract.py lo audita.
    redirect_slashes=False,
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
    return error_response(
        status_code=exc.http_status,
        error_code=exc.error_code,
        message=exc.message,
        detail=exc.detail,
        headers=exc.headers,
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    detail = exc.detail
    message = detail if isinstance(detail, str) else "Error de solicitud"
    error_code_by_status = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        429: "RATE_LIMITED",
    }
    return error_response(
        status_code=exc.status_code,
        error_code=error_code_by_status.get(exc.status_code, "HTTP_ERROR"),
        message=message,
        detail=detail if not isinstance(detail, str) else None,
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
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

    readable_msg = (
        "; ".join(error_strings) or "Error de validación en los datos enviados."
    )

    return error_response(
        status_code=422,
        error_code="VALIDATION_ERROR",
        message=readable_msg,
        detail=error_strings,
        # detail es lista de strings — nunca objetos — para que React pueda renderizar
    )


def _concurrent_modification_response() -> JSONResponse:
    return error_response(
        status_code=409,
        error_code="CONCURRENT_MODIFICATION",
        message=(
            "Alguien mas modifico este registro mientras lo editabas. "
            "Actualiza la vista y volve a intentar."
        ),
        headers={"Cache-Control": "no-store"},
    )


@app.exception_handler(StaleDataError)
async def stale_data_exception_handler(
    request: Request, exc: StaleDataError
) -> JSONResponse:
    """Conflicto de concurrencia detectado por el optimistic locking.

    Otra transaccion modifico la fila entre que la leimos y la guardamos. No es
    un fallo del servidor: es una carrera legitima entre dos actores. Se
    responde 409 para que el cliente recargue y reintente, en vez de 500.
    """
    logger.info(
        "stale_data_conflict", path=str(request.url.path), method=request.method
    )
    return _concurrent_modification_response()


# SQLSTATE de Postgres que son carreras legitimas entre transacciones, no
# fallos del servidor: deadlock_detected, serialization_failure y
# lock_not_available.
#
# 55P03 entra porque la migracion `app_role_timeouts` le pone al rol de la app
# `lock_timeout = '5s'`: en una rafaga sobre el mismo profesional, el que
# espera mas de ese plazo por el `SELECT ... FOR UPDATE` recibe 55P03. Es la
# misma carrera entre dos actores que 40P01, provocada por una guarda propia
# del repo, y salia como 500 (AUD2-B7-02, 2026-09-20). La regla de CLAUDE.md
# §4 exige cero 5xx en la prueba de rafaga.
#
# 57014 (statement_timeout) NO entra: ahi no hay otro actor esperando, es una
# consulta que tardo demasiado, o sea un problema del servidor que tiene que
# seguir siendo 500 visible.
_CONCURRENCY_SQLSTATES = frozenset({"40P01", "40001", "55P03"})


# Marca en la propia excepcion de que su `db_error` ya se escribio. Starlette
# 1.0 invoca el handler de una clase concreta DOS veces cuando re-levanta -una
# en el envoltorio de la ruta y otra en `ExceptionMiddleware`-, asi que sin
# esto cada error de base dejaba dos trazas identicas y parecia haber fallado
# dos veces (AUD2-B7-01, seguimiento 2026-09-20).
_ATRIBUTO_YA_LOGUEADO = "_shifty_db_error_logged"


def _sqlstate(exc: DBAPIError) -> str | None:
    """SQLSTATE del error del driver (asyncpg: ``sqlstate``; psycopg: ``pgcode``)."""
    candidatos = [exc.orig, getattr(exc.orig, "__cause__", None)]
    for error in candidatos:
        for atributo in ("sqlstate", "pgcode"):
            valor = getattr(error, atributo, None)
            if isinstance(valor, str):
                return valor
    return None


@app.exception_handler(DBAPIError)
async def dbapi_error_handler(request: Request, exc: DBAPIError) -> JSONResponse:
    """Carrera de locks de Postgres: 409 neutro (S-18, AUD2-B7-02).

    Postgres ya aborto la transaccion; el handler solo responde. Quedan dos
    cruces de locks posibles (reprogramar turno -> profesional contra el alta
    de bloqueos profesionales -> turnos, y el segundo lock del alta publica
    contra un cierre de tienda): son carreras entre dos actores, como el
    optimistic locking, y el cliente reintenta. Sin detalles internos (regla
    20). Cualquier otro error de base es un 500, como antes.

    Ese 500 NO se responde aca: la excepcion se re-levanta. Starlette atiende
    los handlers de clases concretas en `ExceptionMiddleware`, la capa interna,
    que no re-levanta; devolver la respuesta desde aca dejaba mudo a todo error
    de base que no fuera una carrera -conexion perdida, pool agotado, timeouts
    y violacion de politica RLS (42501)-: sin traceback en uvicorn y sin evento
    en Sentry, porque su integracion de Starlette solo reporta excepciones con
    `status_code` (AUD2-B7-01, 2026-09-19). Al subir, la atiende
    `ServerErrorMiddleware` como cualquier otra excepcion: mismo 500 neutro,
    traceback y captura, igual que antes de S-18.

    Al re-levantar, Starlette 1.0 vuelve a invocar este handler (envoltorio de
    la ruta y despues `ExceptionMiddleware`), asi que el log lleva marca en la
    excepcion para escribirse una sola vez.
    """
    sqlstate = _sqlstate(exc)
    if sqlstate in _CONCURRENCY_SQLSTATES:
        logger.warning(
            "db_concurrency_conflict",
            path=str(request.url.path),
            method=request.method,
            sqlstate=sqlstate,
        )
        return _concurrent_modification_response()
    if not getattr(exc, _ATRIBUTO_YA_LOGUEADO, False):
        # El `setattr` va ANTES del log: si el logger fallara, la segunda
        # invocacion tampoco tiene que escribir.
        setattr(exc, _ATRIBUTO_YA_LOGUEADO, True)
        logger.error(
            "db_error",
            path=str(request.url.path),
            method=request.method,
            error_type=type(exc).__name__,
            sqlstate=sqlstate,
            exc_info=True,
        )
    raise exc


@app.exception_handler(IntegrityError)
async def integrity_error_handler(
    request: Request, exc: IntegrityError
) -> JSONResponse:
    """Violacion de una constraint de la DB (unico, FK, check).

    Suele ser una carrera concurrente (dos altas con el mismo email/slug/
    idempotency_key/solape) que el pre-chequeo no puede evitar de forma atomica
    -y bajo RLS a veces ni siquiera ve la fila en conflicto-. Se responde 409
    neutro (sin revelar que fila colisiono ni exponer el SQL) en vez de un 500.
    """
    logger.warning(
        "integrity_conflict", path=str(request.url.path), method=request.method
    )
    return error_response(
        status_code=409,
        error_code="RESOURCE_CONFLICT",
        message="El registro entra en conflicto con uno existente.",
        headers={"Cache-Control": "no-store"},
    )


def _internal_error_response() -> JSONResponse:
    """El 500 neutro, sin log: lo arman dos capas y el evento se registra una."""
    return error_response(
        status_code=500,
        error_code="INTERNAL_SERVER_ERROR",
        message="Error interno del servidor",
        headers={"Cache-Control": "no-store"},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled_exception",
        path=str(request.url.path),
        method=request.method,
        error_type=type(exc).__name__,
    )
    return _internal_error_response()


class LastResortErrorMiddleware:
    """Emite el 500 no manejado DENTRO del stack, no por encima de el.

    El handler de ``Exception`` lo atiende ``ServerErrorMiddleware``, que
    Starlette pone como capa MAS externa de todas: por encima de
    ``CORSMiddleware`` y de ``SecurityHeadersMiddleware``, que solo son las mas
    externas de las de usuario. Esa respuesta salia entonces sin
    ``access-control-allow-origin`` y sin un solo header de seguridad: un
    navegador en otro origen (el dev server de Vite, cualquier cliente
    cross-origin) veia un error de CORS en vez del sobre canonico y el front no
    podia ni mostrar "Error interno del servidor". Ademas el mismo 500 salia
    con headers distintos segun de que capa viniera (AUD2-B7-11, 2026-09-20).

    Esta capa va por dentro de CORS y de los security headers, asi que la
    respuesta los recibe como cualquier otra. La excepcion se RE-LEVANTA igual:
    ``ServerErrorMiddleware`` ve la respuesta ya empezada, no la duplica, y la
    vuelve a levantar para que uvicorn imprima el traceback y el middleware
    ASGI de Sentry capture el evento (la garantia de AUD2-B7-01). El log lo
    escribe el handler de arriba, una sola vez.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracked_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except Exception:
            if response_started:
                # Con la respuesta a medio camino no hay nada que reemplazar:
                # el error sube y el servidor corta la conexion.
                raise
            await _internal_error_response()(scope, receive, send)
            raise


# IMPORTANTE: En Starlette/FastAPI, los middlewares se ejecutan en orden INVERSO al de registro.
# Registramos de lo más interno a lo más externo:
# tenant -> rate limit -> request guard -> boot error -> canonical JSON ->
# last resort -> security headers -> CORS.
app.add_middleware(TenantMiddleware)
app.add_middleware(RedisRateLimitMiddleware)
app.add_middleware(RequestGuardMiddleware)
app.add_middleware(BootErrorMiddleware)
app.add_middleware(CanonicalJsonMiddleware)
# Justo por dentro de los headers de seguridad y de CORS: es lo que hace que el
# 500 no manejado salga con ellos (AUD2-B7-11). Por fuera del sobre canonico
# para cubrir tambien lo que reviente ahi.
app.add_middleware(LastResortErrorMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# Configurar CORS como la capa más externa.
# Obtenemos los orígenes de la configuración y nos aseguramos de que no haya espacios.
origins = [o.strip() for o in settings.CORS_ORIGINS.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    # Con credenciales, el navegador no acepta un wildcard opaco en preflight.
    # Declaramos explícitamente los headers que el frontend realmente usa.
    allow_headers=[
        "Accept",
        "Accept-Language",
        "Authorization",
        "Content-Language",
        "Content-Type",
        "X-Requested-With",
        "X-Idempotency-Key",
    ],
    expose_headers=["X-Idempotency-Key", "Content-Disposition"],
    max_age=600,
)

# La mas externa de todas: todo log del request -incluidos los del rate limit,
# los de CORS y el del 500 no manejado- lleva el request_id del borde.
app.add_middleware(RequestIdMiddleware)

# 3. Registrar Routers
# Una tienda suspendida no escribe desde el panel (la lectura sigue). Va a
# nivel router para que un endpoint de escritura nuevo quede cubierto solo;
# el housekeeping permitido esta por endpoint y verbo en
# SUSPENSION_ALLOWED_WRITES (modules/billing/dependencies.py). TODO router del
# panel lleva la guarda; los unicos exentos son los de abajo, con su motivo, y
# tests/integration/test_suspension_por_endpoint.py falla si aparece una
# escritura fuera de las dos listas (B7-02, 2026-09-19).
_SUSPENSION_GUARD = [Depends(block_writes_when_suspended)]
# Exento: login, logout, sesiones y contrasena (el dueno tiene que poder entrar
# a pagar).
app.include_router(auth_router)
app.include_router(services_router, dependencies=_SUSPENSION_GUARD)
app.include_router(staff_router, dependencies=_SUSPENSION_GUARD)
app.include_router(appointments_router, dependencies=_SUSPENSION_GUARD)
app.include_router(dashboard_router, dependencies=_SUSPENSION_GUARD)
app.include_router(users_router, dependencies=_SUSPENSION_GUARD)
app.include_router(reports_router, dependencies=_SUSPENSION_GUARD)
app.include_router(stores_router, dependencies=_SUSPENSION_GUARD)
app.include_router(appointment_blocks_router, dependencies=_SUSPENSION_GUARD)
# Pagos lleva la guarda: sus escrituras de panel (cobrar turnos ya tomados,
# operar la pasarela) estan permitidas una por una en SUSPENSION_ALLOWED_WRITES
# y un endpoint de pagos nuevo nace bloqueado. El webhook es anonimo y pasa.
app.include_router(payments_router, dependencies=_SUSPENSION_GUARD)
app.include_router(notifications_router, dependencies=_SUSPENSION_GUARD)
app.include_router(promotions_router, dependencies=_SUSPENSION_GUARD)
app.include_router(ledger_router, dependencies=_SUSPENSION_GUARD)
# Exentos: operacion interna y el superadmin (es quien reactiva la tienda).
app.include_router(ops_router)
app.include_router(superadmin_router)
# Exentos: portal publico anonimo (no hay usuario del que sacar la tienda); la
# regla vive en los handlers que crean obligaciones (B1-06).
app.include_router(public_router)
app.include_router(waitlist_router, dependencies=_SUSPENSION_GUARD)
app.include_router(public_waitlist_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "app": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "online",
    }


@app.get("/me", tags=["Users"])
async def get_me(user: User = Depends(get_current_user)) -> dict[str, Any]:
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
