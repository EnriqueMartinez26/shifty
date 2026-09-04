from datetime import time
from typing import Any

from fastapi import Depends, File, Form, UploadFile
from fastapi.responses import Response
from core.router import CanonicalAPIRouter
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import _apply_tenant_context, get_db, set_tenant_context
from core.exceptions import (
    AppException,
    PermissionDeniedException,
    StoreNotFoundException,
)
from core.feature_flags import is_store_feature_enabled, merge_store_feature_flags
from modules.auth.dependencies import get_current_staff
from modules.stores.mappers import to_store_response
from modules.stores.media import (
    ALLOWED_KINDS,
    MAX_IMAGE_BYTES,
    detect_image_type,
    exceeds_pixel_budget,
)
from modules.stores.model import Store, StoreMedia, StoreSchedule
from modules.stores.schemas import (
    StoreFeatureFlags,
    StoreFeatureFlagsResponse,
    StoreFeatureFlagsUpdate,
    StoreMediaUploadResponse,
    StoreResponse,
    StoreUpdate,
)
from modules.users.model import User, UserRole

router = CanonicalAPIRouter(prefix="/stores", tags=["Stores"])

BusinessHoursPayload = dict[str, list[dict[str, str]]]


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

        period = periods[0]
        store.schedules.append(
            StoreSchedule(
                store_id=store.id,
                day_of_week=day_of_week,
                open_time=time.fromisoformat(period["open"]),
                close_time=time.fromisoformat(period["close"]),
            )
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
) -> StoreResponse:
    if user.role != UserRole.ADMIN:
        raise PermissionDeniedException("cambiar la configuraci?n del negocio")

    store = await _get_current_store(user, db)
    update_data = data.model_dump(exclude_unset=True)

    slug = update_data.get("slug")
    if isinstance(slug, str) and slug != store.slug:
        slug_check = await db.execute(select(Store).where(Store.slug == slug))
        if slug_check.scalar_one_or_none():
            raise AppException(
                "El slug ya est? en uso",
                http_status=400,
                error_code="SLUG_ALREADY_IN_USE",
            )

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
    await db.commit()
    await db.refresh(store)
    return to_store_response(store)


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
    if user.role != UserRole.ADMIN:
        raise PermissionDeniedException("cambiar la configuraci?n del negocio")

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
    if user.role != UserRole.ADMIN:
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
    media_id: str,
    db: AsyncSession = Depends(get_db),
) -> Response:
    # Publico: el portal de reservas muestra el logo sin login. Se lee por id
    # bajando el filtro RLS por tienda (como el resto de las lecturas publicas);
    # el id es un ULID no adivinable y la imagen es publica por naturaleza.
    set_tenant_context(None, is_admin=True)
    try:
        await _apply_tenant_context(db)
        result = await db.execute(select(StoreMedia).where(StoreMedia.id == media_id))
        media = result.scalar_one_or_none()
    finally:
        set_tenant_context(None, False)

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
