from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.appointments.model import Appointment, AppointmentStatus
from modules.ledger.model import CustomerLedger
from modules.payments.model import Payment, PaymentStatus
from modules.reports.schemas import (
    ReportClientStats,
    ReportDebtClientItem,
    ReportDebtSummary,
    ProfessionalReportItem,
    ProfessionalReportsResponse,
    ReportAppointmentItem,
    ReportTopClientItem,
    ReportTopServiceItem,
    ReportSummaryResponse,
    ReportSummaryStats,
)
from modules.services.model import Service
from modules.staff.model import Schedule, Staff, StaffBlock
from modules.users.model import User

MetricBucket = dict[str, Any]


class ReportService:
    def __init__(self, db: AsyncSession):
        self.db = db

    def _resolve_date_range(
        self, from_date: date | None, to_date: date | None
    ) -> tuple[date, date]:
        today = datetime.now(timezone.utc).date()
        resolved_to = to_date or today
        resolved_from = from_date or (resolved_to - timedelta(days=30))

        if resolved_from > resolved_to:
            raise ValueError("from_date no puede ser mayor a to_date")

        return resolved_from, resolved_to

    def _range_bounds(
        self, from_date: date, to_date: date
    ) -> tuple[datetime, datetime]:
        start_dt = datetime.combine(from_date, time.min)
        end_dt = datetime.combine(to_date + timedelta(days=1), time.min)
        return start_dt, end_dt

    def _empty_debt_summary(self) -> ReportDebtSummary:
        return ReportDebtSummary(
            outstanding_balance=0.0,
            debtors_count=0,
            average_debt=0.0,
            top_debtors=[],
        )

    def _user_display_name(
        self,
        user: User | None,
        *,
        fallback: str | None = None,
        client_id: str | None = None,
    ) -> str:
        if user:
            full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
            if full_name:
                return full_name
            if user.email:
                return user.email
            if user.phone:
                return user.phone
        if fallback:
            return fallback
        return client_id or "Cliente"

    async def _build_debt_summary(self) -> ReportDebtSummary:
        result = await self.db.execute(
            select(CustomerLedger).order_by(
                CustomerLedger.client_id.asc(), CustomerLedger.created_at.asc()
            )
        )
        latest_by_client: dict[str, CustomerLedger] = {}
        for movement in result.scalars().all():
            latest_by_client[movement.client_id] = movement

        debt_rows = [
            movement
            for movement in latest_by_client.values()
            if Decimal(str(movement.balance_after or 0)) > 0
        ]
        if not debt_rows:
            return self._empty_debt_summary()

        client_ids = [
            movement.client_id for movement in debt_rows if movement.client_id
        ]
        users_result = await self.db.execute(
            select(User).where(User.id.in_(client_ids))
        )
        users_by_id = {user.id: user for user in users_result.scalars().all()}

        total_balance = sum(
            (Decimal(str(item.balance_after or 0)) for item in debt_rows),
            Decimal("0.00"),
        )
        top_debtors = sorted(
            debt_rows,
            key=lambda item: (Decimal(str(item.balance_after or 0)), item.created_at),
            reverse=True,
        )[:5]
        top_debtor_items: list[ReportDebtClientItem] = []
        for item in top_debtors:
            client_id = item.client_id or ""
            top_debtor_items.append(
                ReportDebtClientItem(
                    client_id=client_id,
                    client_name=self._user_display_name(
                        users_by_id.get(client_id),
                        client_id=client_id,
                    ),
                    balance=round(float(Decimal(str(item.balance_after or 0))), 2),
                )
            )

        return ReportDebtSummary(
            outstanding_balance=round(float(total_balance), 2),
            debtors_count=len(debt_rows),
            average_debt=round(float(total_balance / len(debt_rows)), 2),
            top_debtors=top_debtor_items,
        )

    async def _fetch_rows(
        self,
        *,
        from_date: date,
        to_date: date,
        staff_id: str | None = None,
    ) -> list[tuple[Appointment, Service, Staff, User]]:
        start_dt, end_dt = self._range_bounds(from_date, to_date)
        query = (
            select(Appointment, Service, Staff, User)
            .join(Service, Appointment.service_id == Service.id)
            .join(Staff, Appointment.staff_id == Staff.id)
            .join(User, Appointment.client_id == User.id)
            .where(Appointment.starts_at >= start_dt, Appointment.starts_at < end_dt)
            .order_by(Appointment.starts_at.asc())
        )
        if staff_id:
            query = query.where(Appointment.staff_id == staff_id)
        result = await self.db.execute(query)
        return cast(
            list[tuple[Appointment, Service, Staff, User]],
            result.all(),
        )

    async def _accredited_payments_by_appointment(
        self, appointment_ids: list[str]
    ) -> dict[str, Decimal]:
        """Suma, por turno, la plata acreditada (aprobada o confirmada manual).

        Se acota a los ids de turnos ya cargados (propios del tenant), asi que
        no puede sumar cobros de otra tienda.
        """
        if not appointment_ids:
            return {}
        result = await self.db.execute(
            select(Payment.appointment_id, Payment.amount).where(
                Payment.appointment_id.in_(appointment_ids),
                Payment.status.in_(
                    [
                        PaymentStatus.APPROVED.value,
                        PaymentStatus.MANUAL_CONFIRMED.value,
                    ]
                ),
            )
        )
        acumulado: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
        for appointment_id, amount in result.all():
            acumulado[appointment_id] += amount or Decimal("0.00")
        return acumulado

    async def get_summary(
        self,
        from_date: date | None,
        to_date: date | None,
        *,
        staff_id: str | None = None,
    ) -> ReportSummaryResponse:
        resolved_from, resolved_to = self._resolve_date_range(from_date, to_date)
        start_dt, end_dt = self._range_bounds(resolved_from, resolved_to)
        rows = await self._fetch_rows(
            from_date=resolved_from, to_date=resolved_to, staff_id=staff_id
        )
        # Ingreso = plata efectivamente cobrada, no turnos agendados. La fuente
        # de verdad es el pago acreditado (Mercado Pago aprobado, o cobro manual
        # que el dueno confirma por efectivo/WhatsApp). Un turno confirmado pero
        # sin pago acreditado es una reserva, no un ingreso. El monto ya viene
        # con el descuento de la promo aplicado y al precio historico, asi que
        # esto tambien resuelve el precio de lista y las promociones.
        paid_by_appt = await self._accredited_payments_by_appointment(
            [appointment.id for appointment, *_ in rows]
        )
        historical_clients_query = (
            select(
                Appointment.client_id,
                User.first_name,
                User.last_name,
                User.email,
                Appointment.starts_at,
            )
            .join(User, Appointment.client_id == User.id)
            .where(Appointment.client_id.is_not(None), Appointment.starts_at < end_dt)
        )
        if staff_id:
            historical_clients_query = historical_clients_query.where(
                Appointment.staff_id == staff_id
            )
        historical_clients_result = await self.db.execute(
            historical_clients_query.order_by(Appointment.starts_at.asc())
        )

        items: list[ReportAppointmentItem] = []
        total_revenue = 0.0
        completed = 0
        cancelled = 0
        pending = 0
        confirmed = 0
        clients_in_range: set[str] = set()
        clients_seen_before_range: set[str] = set()
        first_seen_by_client: dict[str, datetime] = {}
        known_client_names: dict[str, str] = {}
        service_metrics: dict[str, MetricBucket] = defaultdict(
            lambda: {
                "service_id": "",
                "service_name": "",
                "appointments": 0,
                "completed_appointments": 0,
                "revenue": 0.0,
            }
        )
        client_metrics: dict[str, MetricBucket] = defaultdict(
            lambda: {
                "client_id": "",
                "client_name": "",
                "appointments": 0,
                "completed_appointments": 0,
                "revenue": 0.0,
            }
        )

        def _client_display_name(
            client: User | None, fallback: str | None = None
        ) -> str:
            if client is None:
                return (fallback or "").strip()
            return client.full_name or client.email or (fallback or "").strip()

        for (
            client_id,
            first_name,
            last_name,
            email,
            starts_at,
        ) in historical_clients_result.all():
            if not client_id:
                continue
            first_seen_by_client.setdefault(client_id, starts_at)
            if starts_at < start_dt:
                clients_seen_before_range.add(client_id)
            resolved_name = _client_display_name(
                None,
                fallback=(
                    f"{first_name or ''} {last_name or ''}".strip()
                    if first_name or last_name
                    else ""
                )
                or email,
            )
            if resolved_name and resolved_name.strip():
                known_client_names.setdefault(client_id, resolved_name.strip())

        for row in rows:
            if len(row) == 4:
                appointment, service, staff, client = row
            else:
                appointment, service, staff = row
                client = None
            status = appointment.status
            # Ingreso real de este turno: lo acreditado, no el precio de lista.
            paid = float(paid_by_appt.get(appointment.id, Decimal("0.00")))
            status_upper = status.upper() if status else ""
            client_id = appointment.client_id
            client_key = client_id or ""
            if client_id:
                clients_in_range.add(client_id)
                current_name = _client_display_name(client, appointment.client_name)
                if current_name:
                    known_client_names[client_id] = current_name

            if status_upper == "COMPLETED":
                completed += 1
            elif status_upper == "CANCELLED":
                cancelled += 1
            elif status_upper in {"PENDING", "PENDING_PAYMENT"}:
                pending += 1
            elif status_upper == "CONFIRMED":
                confirmed += 1
            # El ingreso no depende del estado del turno sino de si se cobro.
            total_revenue += paid

            if status not in {
                AppointmentStatus.CANCELLED.value,
                AppointmentStatus.EXPIRED.value,
            }:
                service_bucket = service_metrics[service.public_id]
                service_bucket["service_id"] = service.public_id
                service_bucket["service_name"] = service.name
                service_bucket["appointments"] += 1
                if status == AppointmentStatus.COMPLETED.value:
                    service_bucket["completed_appointments"] += 1
                service_bucket["revenue"] += paid

                if client_id:
                    client_bucket = client_metrics[client_key]
                    client_bucket["client_id"] = client_key
                    client_bucket["client_name"] = (
                        known_client_names.get(client_key)
                        or _client_display_name(client, appointment.client_name)
                        or client_key
                    )
                    client_bucket["appointments"] += 1
                    if status == AppointmentStatus.COMPLETED.value:
                        client_bucket["completed_appointments"] += 1
                    client_bucket["revenue"] += paid

            resolved_client_name = (
                _client_display_name(client, appointment.client_name)
                or known_client_names.get(client_key, "")
                or "Cliente"
            )

            items.append(
                ReportAppointmentItem(
                    public_id=appointment.public_id,
                    starts_at=appointment.starts_at,
                    ends_at=appointment.ends_at,
                    status=status,
                    service_name=service.name,
                    staff_name=staff.display_name,
                    client_name=resolved_client_name,
                    # Precio del turno: el congelado al reservar; si es un turno
                    # viejo sin snapshot, el precio de lista actual.
                    service_price=float(
                        appointment.price_amount
                        if appointment.price_amount is not None
                        else service.price
                    ),
                )
            )

        total = len(items)
        average_ticket = (total_revenue / total) if total else 0.0
        new_clients = sum(
            1
            for client_id in clients_in_range
            if start_dt <= first_seen_by_client.get(client_id, start_dt) < end_dt
        )
        top_services = sorted(
            service_metrics.values(),
            key=lambda item: (item["appointments"], item["revenue"]),
            reverse=True,
        )[:5]
        top_clients = sorted(
            client_metrics.values(),
            key=lambda item: (item["appointments"], item["revenue"]),
            reverse=True,
        )[:5]

        stats = ReportSummaryStats(
            total_appointments=total,
            completed_appointments=completed,
            cancelled_appointments=cancelled,
            pending_appointments=pending,
            confirmed_appointments=confirmed,
            total_revenue=round(total_revenue, 2),
            average_ticket=round(average_ticket, 2),
        )
        client_stats = ReportClientStats(
            total_clients=len(clients_in_range),
            new_clients=new_clients,
            returning_clients=max(len(clients_in_range) - new_clients, 0),
            inactive_clients=len(clients_seen_before_range - clients_in_range),
        )
        debt_summary = (
            self._empty_debt_summary() if staff_id else await self._build_debt_summary()
        )

        return ReportSummaryResponse(
            from_date=resolved_from,
            to_date=resolved_to,
            stats=stats,
            client_stats=client_stats,
            top_services=[
                ReportTopServiceItem(
                    service_id=item["service_id"],
                    service_name=item["service_name"],
                    appointments=item["appointments"],
                    completed_appointments=item["completed_appointments"],
                    revenue=round(item["revenue"], 2),
                )
                for item in top_services
            ],
            top_clients=[
                ReportTopClientItem(
                    client_id=item["client_id"],
                    client_name=item["client_name"],
                    appointments=item["appointments"],
                    completed_appointments=item["completed_appointments"],
                    revenue=round(item["revenue"], 2),
                )
                for item in top_clients
            ],
            debt_summary=debt_summary,
            appointments=items,
        )

    async def get_professionals(
        self,
        from_date: date | None,
        to_date: date | None,
        *,
        only_staff_id: str | None = None,
    ) -> ProfessionalReportsResponse:
        resolved_from, resolved_to = self._resolve_date_range(from_date, to_date)
        start_dt, end_dt = self._range_bounds(resolved_from, resolved_to)

        staff_query = select(Staff).where(Staff.is_active.is_(True))
        if only_staff_id:
            staff_query = staff_query.where(Staff.id == only_staff_id)
        staff_result = await self.db.execute(
            staff_query.order_by(Staff.display_name.asc())
        )
        staff_members = list(staff_result.scalars().all())
        staff_ids = [staff.id for staff in staff_members]
        if not staff_ids:
            return ProfessionalReportsResponse(
                from_date=resolved_from, to_date=resolved_to, professionals=[]
            )

        schedules_result = await self.db.execute(
            select(Schedule).where(Schedule.staff_id.in_(staff_ids))
        )
        blocks_result = await self.db.execute(
            select(StaffBlock).where(
                StaffBlock.staff_id.in_(staff_ids),
                StaffBlock.is_active.is_(True),
                StaffBlock.starts_at < end_dt,
                StaffBlock.ends_at > start_dt,
            )
        )
        rows = await self._fetch_rows(
            from_date=resolved_from, to_date=resolved_to, staff_id=only_staff_id
        )

        schedules_by_staff: dict[str, list[Schedule]] = defaultdict(list)
        for schedule in schedules_result.scalars().all():
            schedules_by_staff[schedule.staff_id].append(schedule)

        blocks_by_staff: dict[str, list[StaffBlock]] = defaultdict(list)
        for block in blocks_result.scalars().all():
            blocks_by_staff[block.staff_id].append(block)

        appointments_by_staff: dict[str, list[tuple[Appointment, Service, Staff]]] = (
            defaultdict(list)
        )
        for row in rows:
            appointment, service, staff = row[:3]
            appointments_by_staff[staff.id].append((appointment, service, staff))

        # Mismo criterio que el resumen: ingreso = plata acreditada por turno.
        paid_by_appt = await self._accredited_payments_by_appointment(
            [appointment.id for appointment, *_ in rows]
        )

        items: list[ProfessionalReportItem] = []
        total_days = (resolved_to - resolved_from).days + 1

        for staff in staff_members:
            available_minutes = 0
            for schedule in schedules_by_staff.get(staff.id, []):
                daily_minutes = int(
                    (
                        datetime.combine(date.min, schedule.end_time)
                        - datetime.combine(date.min, schedule.start_time)
                    ).total_seconds()
                    // 60
                )
                matching_days = sum(
                    1
                    for offset in range(total_days)
                    if (resolved_from + timedelta(days=offset)).weekday()
                    == schedule.day_of_week
                )
                available_minutes += daily_minutes * matching_days

            blocked_minutes = 0
            for block in blocks_by_staff.get(staff.id, []):
                clipped_start = max(block.starts_at.replace(tzinfo=None), start_dt)
                clipped_end = min(block.ends_at.replace(tzinfo=None), end_dt)
                if clipped_end > clipped_start:
                    blocked_minutes += int(
                        (clipped_end - clipped_start).total_seconds() // 60
                    )

            total_appointments = 0
            completed = 0
            confirmed = 0
            absent = 0
            cancelled = 0
            used_minutes = 0
            revenue = 0.0

            for appointment, service, _ in appointments_by_staff.get(staff.id, []):
                total_appointments += 1
                if appointment.status not in {
                    AppointmentStatus.CANCELLED.value,
                    AppointmentStatus.EXPIRED.value,
                }:
                    used_minutes += int(appointment.duration_minutes)
                if appointment.status == AppointmentStatus.COMPLETED.value:
                    completed += 1
                elif appointment.status == AppointmentStatus.CONFIRMED.value:
                    confirmed += 1
                elif appointment.status == AppointmentStatus.ABSENT.value:
                    absent += 1
                elif appointment.status == AppointmentStatus.CANCELLED.value:
                    cancelled += 1
                # El ingreso del profesional es lo cobrado, no lo agendado.
                revenue += float(paid_by_appt.get(appointment.id, Decimal("0.00")))

            effective_minutes = max(available_minutes - blocked_minutes, 0)
            occupancy_rate = (
                round((used_minutes / effective_minutes) * 100, 2)
                if effective_minutes
                else 0.0
            )
            items.append(
                ProfessionalReportItem(
                    staff_id=staff.public_id,
                    staff_name=staff.display_name,
                    appointments=total_appointments,
                    completed_appointments=completed,
                    confirmed_appointments=confirmed,
                    absent_appointments=absent,
                    cancelled_appointments=cancelled,
                    used_minutes=used_minutes,
                    used_hours=round(used_minutes / 60, 2),
                    available_minutes=available_minutes,
                    available_hours=round(available_minutes / 60, 2),
                    blocked_minutes=blocked_minutes,
                    blocked_hours=round(blocked_minutes / 60, 2),
                    occupancy_rate=occupancy_rate,
                    revenue=round(revenue, 2),
                )
            )

        return ProfessionalReportsResponse(
            from_date=resolved_from,
            to_date=resolved_to,
            professionals=items,
        )
