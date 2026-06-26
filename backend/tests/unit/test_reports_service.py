from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from modules.reports.schemas import ReportDebtSummary
from modules.reports.service import ReportService


@pytest.mark.asyncio
async def test_report_summary_uses_safe_client_name_fallback() -> None:
    fake_db = SimpleNamespace()
    service = ReportService(db=cast(AsyncSession, fake_db))
    appointment = SimpleNamespace(
        public_id="appt-1",
        starts_at=datetime(2026, 6, 15, 10, 0, tzinfo=timezone.utc),
        ends_at=datetime(2026, 6, 15, 10, 30, tzinfo=timezone.utc),
        status="completed",
        client_id=None,
        client_name=None,
        duration_minutes=30,
        intake_answers=None,
    )
    service_model = SimpleNamespace(
        public_id="svc-1",
        name="Consulta",
        price=10000,
    )
    staff_model = SimpleNamespace(display_name="Pro Demo")

    async def fake_fetch_rows(
        *, from_date: Any, to_date: Any, staff_id: Any = None
    ) -> list[tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace]]:
        return [(appointment, service_model, staff_model)]

    async def fake_empty_debt_summary() -> ReportDebtSummary:
        return ReportDebtSummary(
            outstanding_balance=0.0,
            debtors_count=0,
            average_debt=0.0,
            top_debtors=[],
        )

    async def fake_execute(*args: Any, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(all=lambda: [])

    fake_db.execute = fake_execute
    service_any = cast(Any, service)
    service_any._fetch_rows = fake_fetch_rows
    service_any._build_debt_summary = fake_empty_debt_summary

    summary = await service.get_summary(None, None)

    assert summary.stats.total_appointments == 1
    assert summary.appointments[0].client_name == "Cliente"
