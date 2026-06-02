from datetime import date
from io import BytesIO

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from modules.auth.dependencies import get_current_admin
from modules.users.model import User
from modules.reports.exporter import export_to_csv, export_to_excel, export_to_pdf
from modules.reports.schemas import ReportExportRequest, ReportSummaryResponse
from modules.reports.service import ReportService

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("/summary", response_model=ReportSummaryResponse)
async def get_report_summary(
    from_date: date | None = None,
    to_date: date | None = None,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    service = ReportService(db)
    try:
        return await service.get_summary(from_date, to_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/export")
async def export_report(
    payload: ReportExportRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    service = ReportService(db)
    try:
        summary = await service.get_summary(payload.from_date, payload.to_date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        if payload.format == "csv":
            file_bytes = export_to_csv(summary)
            media_type = "text/csv"
            extension = "csv"
        elif payload.format == "excel":
            file_bytes = export_to_excel(summary)
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            extension = "xlsx"
        else:
            file_bytes = export_to_pdf(summary)
            media_type = "application/pdf"
            extension = "pdf"
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    filename = f"{payload.filename_prefix}-{summary.from_date.isoformat()}-{summary.to_date.isoformat()}.{extension}"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(BytesIO(file_bytes), media_type=media_type, headers=headers)
