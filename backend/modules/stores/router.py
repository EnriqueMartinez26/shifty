from datetime import time
from typing import Annotated, Any

import structlog
from fastapi import Depends, File, Form, Path, UploadFile
from fastapi.responses import Response
from core.router import CanonicalAPIRouter
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.availability_cache import invalidate_store_availability
from core.database import get_db, tenant_bypass
from core.exceptions import (
    AppException,
    PermissionDeniedException,
    StoreNotFoundException,
)
from core.feature_flags import is_store_feature_enabled, merge_store_feature_flags
from core.redis import get_redis
from core.roles import STORE_MANAGERS, has_any_role
from core.validation import PUBLIC_ID_PATTERN
from modules.auth.dependencies import get_current_staff
from modules.stores.mappers import to_store_response
from modules.stores.media import (
    ALLOWED_KINDS,
    MAX_IMAGE_BYTES,
    detect_image_type,
    exceeds_pixel_budget,
)
from modules.stores.model import Store, StoreMedia, StoreSchedule
from modules.billing.service import get_active_subscription, today_local
from modules.billing.subscription_rules import outlook
from modules.stores.schemas import (
    StoreFeatureFlags,
    StoreFeatureFlagsResponse,
    StoreFeatureFlagsUpdate,
    StoreMediaUploadResponse,
    StoreResponse,
    StoreSubscriptionStatusResponse,
    StoreUpdate,
)
from modules.users.model import User

logger = structlog.get_logger()
router = CanonicalAPIRouter(prefix="/stores", tags=["Stores"])
PublicIdPath = Annotated[
    str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)
]

# Ya validado por BusinessHourPeriod: horas reales y open < close.
BusinessHoursPayload = dict[str, list[dict[str, time]]]


async def _get_current_store(user: User, db: AsyncSession) -> Store:
    result = await db.execute(select(Store).where(Store.id == user.store_id))
    store = result.scalar_one_or_none()
    if not store:
        raise StoreNotFoundException(user.store_id)
    return store


def _replace_business_hours(
    store: Store, business_hours: BusinessHoursPayload | None
) -> None:
    if business_hours is None:
        return

    days_map = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
    store.schedules.clear()

    for day_key, periods in business_hours.items():
        day_of_week = days_map.get(day_key)
        if day_of_week is None or not periods:
            continue

        # Un solo periodo por dia: ``StoreUpdate.reject_extra_periods`` da 422
        # ante un segundo, asi que aca ya no se pierde nada en silencio
        # (AUD2-B3-07). Soportar horario partido es producto, y esta pendiente.
        period = periods[0]
        store.schedules.append(
            StoreSchedule(
                store_id=store.id,
                day_of_week=day_of_week,
                open_time=period["open"],
                close_time=period["close"],
            )
        )


# Campos del local que son insumo de la grilla de disponibilidad: el horario
# comercial, el hueco obligatorio entre turnos y la antelacion minima. Cambiar
# uno cambia lo que el portal puede ofrecer cualquier dia, asi que invalida la
# generacion de la tienda entera, no un dia (AUD2-B3-05).
_CAMPOS_DE_AGENDA = frozenset(
    {"business_hours", "buffer_minutes", "min_booking_notice_hours"}
)


async def _invalidar_agenda(redis: Redis, store_id: str) -> None:
    """Best-effort DESPUES del commit, igual que ``services/router.py``.

    Un Redis caido no revierte la configuracion ya guardada; en el peor caso
    el portal muestra lo viejo hasta que vencen los slots (300 s).
    """
    try:
        await invalidate_store_availability(redis, store_id)
    except RedisError as exc:
        logger.warning(
            "store_cache_invalidation_failed",
            store_id=store_id,
            error_type=type(exc).__name__,
        )


@router.get("/me", response_model=StoreResponse)
async def get_my_store(
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> StoreResponse:
    store = await _get_current_store(user, db)
    return to_store_response(store)


@router.patch("/me", response_model=StoreResponse)
async def update_my_store(
    data: StoreUpdate,
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> StoreResponse:
    # Rol canonico de core/roles.py, no el enum crudo (B3-18): un superadmin
    # cuyo role no sea 'admin' quedaba afuera, y era una segunda llave de rol
    # como la que auth/dependencies.py ya elimino.
    if not has_any_role(user, STORE_MANAGERS):
        raise PermissionDeniedException("cambiar la configuración del negocio")

    store = await _get_current_store(user, db)
    update_data = data.model_dump(exclude_unset=True)
    toca_la_agenda = bool(_CAMPOS_DE_AGENDA & update_data.keys())

    # El slug duplicado lo decide el UNIQUE de `stores.slug`, no un pre-chequeo
    # (AUD2-B3-15): bajo RLS ese chequeo nunca veia la otra tienda. El porque
    # completo vive en tests/integration/test_slug_duplicado_de_tienda.py.

    # Contracara de la validacion en feature-flags: si los cobros ya estan
    # activos, vaciar la politica dejaria al cliente aceptando un texto que ya
    # no existe.
    if "deposit_policy" in update_data:
        policy = (update_data.get("deposit_policy") or "").strip()
        payments_enabled = is_store_feature_enabled(store.feature_flags, "payments")
        if not policy and payments_enabled:
            raise AppException(
                "No podes dejar vacia la politica de sena mientras los cobros "
                "online esten activos",
                http_status=422,
                error_code="DEPOSIT_POLICY_REQUIRED",
            )
        update_data["deposit_policy"] = policy or None

    raw_business_hours = update_data.pop("business_hours", None)
    business_hours = (
        raw_business_hours if isinstance(raw_business_hours, dict) else None
    )
    theme_keys = (
        "business_type",
        "cover_url",
        "description",
        "whatsapp_number",
        "instagram_url",
        "facebook_url",
        "website_url",
        "custom_client_fields",
    )
    theme_config: dict[str, Any] = dict(store.theme_config or {})
    for key in theme_keys:
        if key in update_data:
            theme_config[key] = update_data.pop(key)
    store.theme_config = theme_config

    for key, value in update_data.items():
        setattr(store, key, value)

    _replace_business_hours(store, business_hours)
    try:
        await db.commit()
    except IntegrityError:
        # Mismo patron que `UserService.create`: rollback y re-raise para que el
        # handler global responda 409 neutro con la SESION SANA. Sin el
        # rollback, la sesion queda en `PendingRollbackError` y cualquier
        # consulta posterior de la misma request revienta con un error que no
        # tiene nada que ver (AUD2-B3-15). Este router es dueno de su
        # transaccion por deuda declarada de CLAUDE.md; migrarlo a un service
        # es otro trabajo, pero la sesion tiene que quedar usable igual.
        await db.rollback()
        raise
    await db.refresh(store)
    if toca_la_agenda:
        await _invalidar_agenda(redis, str(store.id))
    return to_store_response(store)


@router.get("/me/subscription", response_model=StoreSubscriptionStatusResponse)
async def get_my_subscription(
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> StoreSubscriptionStatusResponse:
    """Estado del plan de la tienda para el banner del panel."""
    subscription = await get_active_subscription(db, user.store_id)
    vista = outlook(subscription, today=today_local())
    return StoreSubscriptionStatusResponse(
        status=vista.status,
        plan_name=getattr(subscription, "plan_name", None) if subscription else None,
        current_period_end=getattr(subscription, "current_period_end", None)
        if subscription
        else None,
        days_left=vista.days_left,
        grace_until=vista.grace_until_day,
        warn=vista.warn,
        blocks_writes=vista.blocks_writes,
    )


@router.get("/me/feature-flags", response_model=StoreFeatureFlagsResponse)
async def get_my_store_feature_flags(
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> StoreFeatureFlagsResponse:
    store = await _get_current_store(user, db)
    return StoreFeatureFlagsResponse(
        flags=StoreFeatureFlags.model_validate(store.normalized_feature_flags)
    )


@router.put("/me/feature-flags", response_model=StoreFeatureFlagsResponse)
async def update_my_store_feature_flags(
    data: StoreFeatureFlagsUpdate,
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> StoreFeatureFlagsResponse:
    if not has_any_role(user, STORE_MANAGERS):
        raise PermissionDeniedException("cambiar la configuración del negocio")

    store = await _get_current_store(user, db)
    updates = data.model_dump(exclude_unset=True)
    # No se puede cobrar una sena sin publicar bajo que condiciones se cobra:
    # el cliente acepta esa politica antes de pagar y es el respaldo ante un
    # reclamo. Sin ella, el consentimiento no tiene contenido.
    if updates.get("payments") and not (store.deposit_policy or "").strip():
        raise AppException(
            "Para activar los cobros online primero tenes que publicar tu "
            "politica de sena, cancelacion y reembolso",
            http_status=422,
            error_code="DEPOSIT_POLICY_REQUIRED",
        )
    store.feature_flags = merge_store_feature_flags(
        store.feature_flags,
        updates,
    )
    await db.commit()
    await db.refresh(store)
    return StoreFeatureFlagsResponse(
        flags=StoreFeatureFlags.model_validate(store.normalized_feature_flags)
    )


@router.post("/me/media", response_model=StoreMediaUploadResponse)
async def upload_store_media(
    kind: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> StoreMediaUploadResponse:
    if not has_any_role(user, STORE_MANAGERS):
        raise PermissionDeniedException("cambiar la imagen del negocio")
    if kind not in ALLOWED_KINDS:
        raise AppException(
            "Tipo de imagen invalido",
            http_status=422,
            error_code="INVALID_MEDIA_KIND",
        )

    # Cota de tamano antes de materializar: se leen a lo sumo MAX+1 bytes para
    # distinguir "justo en el limite" de "se paso" sin cargar un blob gigante.
    data = await file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise AppException(
            "La imagen supera el maximo de 2 MB",
            http_status=413,
            error_code="MEDIA_TOO_LARGE",
        )
    if not data:
        raise AppException("Archivo vacio", http_status=422, error_code="EMPTY_MEDIA")

    # Validacion por MAGIC BYTES, no por el Content-Type declarado (falsificable).
    # SVG queda excluido: puede ejecutar JS y volverse XSS al servirse inline.
    content_type = detect_image_type(data)
    if content_type is None:
        raise AppException(
            "Formato no permitido. Solo PNG, JPEG o WebP.",
            http_status=422,
            error_code="UNSUPPORTED_MEDIA_TYPE",
        )

    # Dentro de 2MB entra una imagen que declara dimensiones enormes (bomba de
    # pixeles): rechaza el navegador del visitante al decodificarla.
    if exceeds_pixel_budget(data, content_type):
        raise AppException(
            "La imagen tiene demasiados pixeles (maximo 25 megapixeles).",
            http_status=422,
            error_code="IMAGE_TOO_LARGE_DIMENSIONS",
        )

    store = await _get_current_store(user, db)

    # Una imagen por tipo y tienda: se borran las anteriores del mismo kind para
    # no acumular huerfanos en la tabla.
    await db.execute(
        delete(StoreMedia).where(
            StoreMedia.store_id == store.id, StoreMedia.kind == kind
        )
    )
    media = StoreMedia(
        store_id=store.id,
        kind=kind,
        content_type=content_type,
        byte_size=len(data),
        data=data,
    )
    db.add(media)
    await db.flush()

    url = f"/api/stores/media/{media.id}"
    if kind == "logo":
        store.logo_url = url
    else:
        # cover vive en theme_config, como el resto de los campos de tema.
        theme_config = dict(store.theme_config or {})
        theme_config["cover_url"] = url
        store.theme_config = theme_config

    await db.commit()
    return StoreMediaUploadResponse(url=url, media_id=media.id, kind=kind)


@router.get("/media/{media_id}")
async def serve_store_media(
    # Validado como el resto de los path params (B3-17): la ruta es publica y
    # consulta bajo bypass de RLS; un id fuera del patron no llega a la base.
    media_id: PublicIdPath,
    db: AsyncSession = Depends(get_db),
) -> Response:
    # Publico: el portal de reservas muestra el logo sin login. Se lee por id
    # bajando el filtro RLS por tienda (como el resto de las lecturas publicas);
    # el id es un ULID no adivinable y la imagen es publica por naturaleza.
    async with tenant_bypass(db):
        result = await db.execute(select(StoreMedia).where(StoreMedia.id == media_id))
        media = result.scalar_one_or_none()

    if media is None:
        raise AppException(
            "Imagen no encontrada", http_status=404, error_code="MEDIA_NOT_FOUND"
        )

    return Response(
        content=media.data,
        media_type=media.content_type,
        headers={
            "Cache-Control": "public, max-age=86400",
            "Content-Disposition": "inline",
        },
    )
