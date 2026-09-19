from collections.abc import Iterable
from datetime import date
from io import BytesIO

from fastapi import Depends, Query
from core.router import CanonicalAPIRouter
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.exceptions import AppException, PermissionDeniedException

from core.database import get_db
from core.roles import (
    REPORT_EXPORTERS,
    REPORT_VIEWERS,
    ROLE_PROFESSIONAL,
    canonical_role,
    has_any_role,
    store_scope_for,
)
from modules.auth.dependencies import get_current_user
from modules.reports.exporter import export_to_csv, export_to_excel, export_to_pdf
from modules.reports.schemas import (
    ProfessionalReportsResponse,
    ReportExportRequest,
    ReportSummaryResponse,
    ReportTrendResponse,
)
from modules.reports.service import ReportService
from modules.users.model import User

router = CanonicalAPIRouter(prefix="/reports", tags=["Reports"])


def _report_scope_for(
    user: User,
    allowed: Iterable[str] = REPORT_VIEWERS,
    action: str = "ver reportes",
) -> str | None:
    if not has_any_role(user, allowed):
        raise PermissionDeniedException(action)
    # Rol canonico, no el literal legacy "staff" (B5-07): si el vocabulario
    # persistido cambia, el profesional sigue acotado a sus turnos en vez de
    # caer en None y ver la tienda completa.
    if canonical_role(user) == ROLE_PROFESSIONAL and not user.is_global_admin:
        return user.id
    return None


@router.get("/summary", response_model=ReportSummaryResponse)
async def get_report_summary(
    from_date: date | None = None,
    to_date: date | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportSummaryResponse:
    service = ReportService(db, store_id=store_scope_for(user))
    staff_scope = _report_scope_for(user)
    try:
        return await service.get_summary(from_date, to_date, staff_id=staff_scope)
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)


@router.get("/professionals", response_model=ProfessionalReportsResponse)
async def get_professional_reports(
    from_date: date | None = None,
    to_date: date | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfessionalReportsResponse:
    service = ReportService(db, store_id=store_scope_for(user))
    staff_scope = _report_scope_for(user)
    try:
        return await service.get_professionals(
            from_date, to_date, only_staff_id=staff_scope
        )
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)


@router.get("/trend", response_model=ReportTrendResponse)
async def get_report_trend(
    months: int = Query(default=6, ge=1, le=24),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReportTrendResponse:
    service = ReportService(db, store_id=store_scope_for(user))
    staff_scope = _report_scope_for(user)
    try:
        return await service.get_trend(months=months, staff_id=staff_scope)
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)


@router.post("/export")
async def export_report(
    payload: ReportExportRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    service = ReportService(db, store_id=store_scope_for(user))
    # Exportar es de admins (B5-06): REPORT_EXPORTERS, no REPORT_VIEWERS. El
    # profesional ve su reporte en pantalla pero no baja el archivo.
    staff_scope = _report_scope_for(
        user, allowed=REPORT_EXPORTERS, action="exportar reportes"
    )
    try:
        summary = await service.get_summary(
            payload.from_date, payload.to_date, staff_id=staff_scope
        )
    except ValueError as exc:
        raise AppException(message=str(exc), http_status=400)

    try:
        if payload.format == "csv":
            file_bytes = export_to_csv(summary)
            media_type = "text/csv"
            extension = "csv"
        elif payload.format == "excel":
            file_bytes = export_to_excel(summary)
            media_type = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            extension = "xlsx"
        else:
            file_bytes = export_to_pdf(summary)
            media_type = "application/pdf"
            extension = "pdf"
    except RuntimeError as exc:
        raise AppException(message=str(exc), http_status=500, error_code="EXPORT_ERROR")

    filename = f"{payload.filename_prefix}-{summary.from_date.isoformat()}-{summary.to_date.isoformat()}.{extension}"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(
        BytesIO(file_bytes), media_type=media_type, headers=headers
    )
