from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from core.utils import today_local
from modules.reports.schemas import ReportDebtSummary
from modules.reports.service import ReportService


@pytest.mark.asyncio
async def test_report_summary_uses_safe_client_name_fallback() -> None:
    """Un turno sin nombre propio ni cliente con datos se muestra como "Cliente".

    La fila tiene las CUATRO columnas que selecciona ``_fetch_rows``
    (turno, servicio, profesional, cliente): el cliente existe pero no tiene
    nombre ni email, y el turno no trae snapshot.
    """
    fake_db = SimpleNamespace()
    service = ReportService(db=cast(AsyncSession, fake_db), store_id="store-1")
    appointment = SimpleNamespace(
        id="appt-1",
        public_id="appt-1",
        starts_at=datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 15, 10, 30, tzinfo=timezone.utc),
        status="completed",
        client_id="cli-1",
        client_name=None,
        duration_minutes=30,
        intake_answers=None,
        price_amount=None,
    )
    service_model = SimpleNamespace(
        public_id="svc-1",
        name="Consulta",
        price=10000,
    )
    staff_model = SimpleNamespace(display_name="Pro Demo")
    client_model = SimpleNamespace(full_name="", email="")

    async def fake_fetch_rows(
        *, from_date: Any, to_date: Any, staff_id: Any = None, page: Any = None
    ) -> list[tuple[SimpleNamespace, ...]]:
        return [(appointment, service_model, staff_model, client_model)]

    async def fake_empty_debt_summary() -> ReportDebtSummary:
        return ReportDebtSummary(
            outstanding_balance=0.0,
            debtors_count=0,
            average_debt=0.0,
            top_debtors=[],
        )

    llamadas: list[int] = []

    async def fake_execute(*args: Any, **kwargs: Any) -> SimpleNamespace:
        # La primera consulta es el conteo por estado (un turno completado);
        # las siguientes son los top-5 (vacios). Cohortes en cero y sin ingreso.
        llamadas.append(1)
        filas = [("completed", 1)] if len(llamadas) == 1 else []
        return SimpleNamespace(
            all=lambda: filas,
            scalar_one=lambda: 0,
            one=lambda: (0, 0, 0),
        )

    fake_db.execute = fake_execute
    service_any = cast(Any, service)
    service_any._fetch_rows = fake_fetch_rows
    service_any._build_debt_summary = fake_empty_debt_summary

    summary = await service.get_summary(None, None)

    assert summary.stats.total_appointments == 1
    assert summary.stats.completed_appointments == 1
    assert summary.appointments[0].client_name == "Cliente"
    assert summary.has_more is False


@pytest.mark.asyncio
async def test_report_trend_fills_gaps_and_counts_by_status() -> None:
    fake_db = SimpleNamespace()
    service = ReportService(db=cast(AsyncSession, fake_db), store_id="store-1")

    # La consulta devuelve la clave 'YYYY-MM' del mes ARGENTINO (S-05), ya
    # calculada en SQL; el mes en curso es el del calendario local.
    current_key = today_local().strftime("%Y-%m")

    async def fake_execute(*args: Any, **kwargs: Any) -> SimpleNamespace:
        # Solo el mes actual tiene turnos: 2 completados, 1 cancelado, 1 pendiente.
        return SimpleNamespace(
            all=lambda: [
                (current_key, "completed", 2),
                (current_key, "cancelled", 1),
                (current_key, "pending", 1),
            ]
        )

    fake_db.execute = fake_execute

    trend = await service.get_trend(months=3)

    assert [point.month for point in trend.points] == sorted(
        point.month for point in trend.points
    )
    assert len(trend.points) == 3
    current_point = next(p for p in trend.points if p.month == current_key)
    assert current_point.total_appointments == 4
    assert current_point.completed_appointments == 2
    assert current_point.cancelled_appointments == 1

    other_points = [p for p in trend.points if p.month != current_key]
    assert all(p.total_appointments == 0 for p in other_points)


@pytest.mark.asyncio
async def test_report_trend_rejects_non_positive_months() -> None:
    fake_db = SimpleNamespace()
    service = ReportService(db=cast(AsyncSession, fake_db), store_id="store-1")

    with pytest.raises(ValueError):
        await service.get_trend(months=0)
