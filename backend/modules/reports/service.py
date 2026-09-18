from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import ColumnElement, Select, Subquery, and_, case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from core.config import settings
from core.utils import ensure_utc_aware, local_day_start, today_local

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
    ReportTrendPoint,
    ReportTrendResponse,
)
from modules.services.model import Service
from modules.staff.model import Schedule, Staff, StaffBlock
from modules.users.model import User

MetricBucket = dict[str, Any]

# Un pago cuenta como ingreso solo si esta acreditado (Mercado Pago aprobado o
# cobro manual confirmado). Mismo criterio que modules/dashboard/repository.py.
_ACCREDITED_PAYMENT_STATUSES = [
    PaymentStatus.APPROVED.value,
    PaymentStatus.MANUAL_CONFIRMED.value,
]
# Un turno cancelado o vencido no cuenta para los top-5 de servicios/clientes.
_EXCLUDED_FROM_TOPS = [
    AppointmentStatus.CANCELLED.value,
    AppointmentStatus.EXPIRED.value,
]


def _report_client_name(client: User | None, fallback: str | None = None) -> str:
    """Nombre a mostrar de un cliente en todo el reporte (B5-18).

    Unica regla, la misma del panel (``dashboard/service.py``): nombre
    completo, si no email, si no el ``fallback`` (el snapshot del turno). El
    telefono NO es un nombre: es PII que el reporte no expone. Los llamadores
    sin fallback usan el ``client_id`` como ultimo recurso.
    """
    if client is None:
        return (fallback or "").strip()
    return client.full_name or client.email or (fallback or "").strip()


def _client_name_from_columns(
    first_name: str | None,
    last_name: str | None,
    email: str | None,
    fallback: str | None,
) -> str:
    """Mismo criterio que ``_report_client_name`` sobre columnas agregadas:
    nombre completo, si no email, si no el snapshot del turno."""
    full_name = f"{first_name or ''} {last_name or ''}".strip()
    return full_name or (email or "").strip() or (fallback or "").strip()


def _add_months(month_start: date, delta: int) -> date:
    """Primer dia del mes que esta `delta` meses despues de `month_start`.

    `month_start` debe ser ya el dia 1 del mes; `delta` puede ser negativo.
    """
    month_index = month_start.month - 1 + delta
    year = month_start.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


def _local_month_key(
    month_starts: list[date], bounds: list[datetime]
) -> ColumnElement[str]:
    """``'YYYY-MM'`` del mes ARGENTINO en que empieza el turno (S-05).

    ``bounds[i]`` es la medianoche argentina del dia 1 de ``month_starts[i]``
    como instante UTC (``local_day_start``). Con el turno ya acotado a
    ``[bounds[0], bounds[-1])``, el primer limite que supera a ``starts_at``
    define su mes. Es SQL portable (Postgres y SQLite) y la zona la resuelve
    zoneinfo en Python, sin corrimiento fijo de -3 horas (regla 24). Antes era
    ``date_trunc('month', starts_at)``: mes UTC, y el 31 a las 22:30 ART caia
    en el mes siguiente.
    """
    return case(
        *(
            (Appointment.starts_at < bounds[i + 1], month_starts[i].strftime("%Y-%m"))
            for i in range(len(month_starts) - 1)
        )
    )


@dataclass
class _SummaryAggregation:
    """Resultado puro de agregar los turnos del rango. Sin I/O: se calcula a
    partir de lo ya traido de la base, y por eso se puede testear aislado."""

    items: list[ReportAppointmentItem] = field(default_factory=list)
    total_appointments: int = 0
    completed: int = 0
    cancelled: int = 0
    pending: int = 0
    confirmed: int = 0
    total_clients: int = 0
    new_clients: int = 0
    returning_clients: int = 0
    inactive_clients: int = 0


@dataclass
class _ClientCohorts:
    """Lo que el historico de clientes aporta al resumen (B5-09).

    ``first_seen``: primera visita de cada cliente; ``seen_before_range``: los
    que ya habian venido antes del inicio del rango; ``known_names``: nombre a
    usar si un turno del rango no trae uno propio.
    """

    first_seen: dict[str, datetime] = field(default_factory=dict)
    seen_before_range: set[str] = field(default_factory=set)
    known_names: dict[str, str] = field(default_factory=dict)


def _client_cohorts(historical_rows: list[Any], start_dt: datetime) -> _ClientCohorts:
    """Cohortes a partir de ``(client_id, nombre, apellido, email, MIN(starts_at))``.

    Las filas ya vienen agregadas por cliente desde la base (regla 11).
    """
    cohorts = _ClientCohorts()
    for client_id, first_name, last_name, email, starts_at in historical_rows:
        if not client_id:
            continue
        # start_dt es UTC aware (ver _range_bounds). Postgres devuelve
        # func.min(starts_at) aware; SQLite, naive: se normaliza a aware antes
        # de comparar (aca y via first_seen) o explota con "can't compare
        # offset-naive and offset-aware datetimes".
        starts_at = ensure_utc_aware(starts_at)
        cohorts.first_seen.setdefault(client_id, starts_at)
        if starts_at < start_dt:
            cohorts.seen_before_range.add(client_id)
        resolved_name = _report_client_name(
            None,
            fallback=(
                f"{first_name or ''} {last_name or ''}".strip()
                if first_name or last_name
                else ""
            )
            or email,
        )
        if resolved_name and resolved_name.strip():
            cohorts.known_names.setdefault(client_id, resolved_name.strip())
    return cohorts


# Estado del turno (en mayusculas) -> contador del resumen. Absent y expired
# solo cuentan en el total.
_STATUS_COUNTERS = {
    "COMPLETED": "completed",
    "CANCELLED": "cancelled",
    "PENDING": "pending",
    "PENDING_PAYMENT": "pending",
    "CONFIRMED": "confirmed",
}


def _unpack_row(row: Any) -> tuple[Appointment, Service, Staff, User | None]:
    if len(row) == 4:
        appointment, service, staff, client = row
        return appointment, service, staff, client
    appointment, service, staff = row
    return appointment, service, staff, None


def _appointment_item(
    appointment: Appointment, service: Service, staff: Staff, client_name: str
) -> ReportAppointmentItem:
    return ReportAppointmentItem(
        public_id=appointment.public_id,
        starts_at=appointment.starts_at,
        ends_at=appointment.ends_at,
        status=appointment.status,
        service_name=service.name,
        staff_name=staff.display_name,
        client_name=client_name,
        # Precio del turno: el congelado al reservar; si es un turno viejo sin
        # snapshot, el precio de lista actual.
        service_price=float(
            appointment.price_amount
            if appointment.price_amount is not None
            else service.price
        ),
    )


def _summary_stats(
    aggregation: _SummaryAggregation, total_revenue: Decimal
) -> ReportSummaryStats:
    revenue = float(total_revenue)
    total = aggregation.total_appointments
    return ReportSummaryStats(
        total_appointments=total,
        completed_appointments=aggregation.completed,
        cancelled_appointments=aggregation.cancelled,
        pending_appointments=aggregation.pending,
        confirmed_appointments=aggregation.confirmed,
        total_revenue=round(revenue, 2),
        average_ticket=round(revenue / total, 2) if total else 0.0,
    )


def _client_stats(aggregation: _SummaryAggregation) -> ReportClientStats:
    return ReportClientStats(
        total_clients=aggregation.total_clients,
        new_clients=aggregation.new_clients,
        returning_clients=aggregation.returning_clients,
        inactive_clients=aggregation.inactive_clients,
    )


def _available_minutes(
    schedules: list[Schedule], from_date: date, total_days: int
) -> int:
    """Minutos de agenda del profesional en los ``total_days`` dias del rango."""
    available_minutes = 0
    for schedule in schedules:
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
            if (from_date + timedelta(days=offset)).weekday() == schedule.day_of_week
        )
        available_minutes += daily_minutes * matching_days
    return available_minutes


def _blocked_minutes(
    blocks: list[StaffBlock], start_dt: datetime, end_dt: datetime
) -> int:
    """Minutos bloqueados, recortando cada bloqueo a ``[start_dt, end_dt)``."""
    blocked_minutes = 0
    for block in blocks:
        clipped_start = max(ensure_utc_aware(block.starts_at), start_dt)
        clipped_end = min(ensure_utc_aware(block.ends_at), end_dt)
        if clipped_end > clipped_start:
            blocked_minutes += int((clipped_end - clipped_start).total_seconds() // 60)
    return blocked_minutes


# Estado del turno -> contador del reporte por profesional.
_PROFESSIONAL_STATUS_COUNTERS = {
    AppointmentStatus.COMPLETED.value: "completed",
    AppointmentStatus.CONFIRMED.value: "confirmed",
    AppointmentStatus.ABSENT.value: "absent",
    AppointmentStatus.CANCELLED.value: "cancelled",
}
_NOT_USING_TIME = {
    AppointmentStatus.CANCELLED.value,
    AppointmentStatus.EXPIRED.value,
}


def _professional_item(
    staff: Staff,
    appointments: list[Appointment],
    *,
    available_minutes: int,
    blocked_minutes: int,
    revenue: float,
) -> ProfessionalReportItem:
    counts: dict[str, int] = defaultdict(int)
    used_minutes = 0
    for appointment in appointments:
        if appointment.status not in _NOT_USING_TIME:
            used_minutes += int(appointment.duration_minutes)
        counter = _PROFESSIONAL_STATUS_COUNTERS.get(appointment.status)
        if counter:
            counts[counter] += 1

    effective_minutes = max(available_minutes - blocked_minutes, 0)
    occupancy_rate = (
        round((used_minutes / effective_minutes) * 100, 2) if effective_minutes else 0.0
    )
    return ProfessionalReportItem(
        staff_id=staff.public_id,
        staff_name=staff.display_name,
        appointments=len(appointments),
        completed_appointments=counts["completed"],
        confirmed_appointments=counts["confirmed"],
        absent_appointments=counts["absent"],
        cancelled_appointments=counts["cancelled"],
        used_minutes=used_minutes,
        used_hours=round(used_minutes / 60, 2),
        available_minutes=available_minutes,
        available_hours=round(available_minutes / 60, 2),
        blocked_minutes=blocked_minutes,
        blocked_hours=round(blocked_minutes / 60, 2),
        occupancy_rate=occupancy_rate,
        revenue=round(revenue, 2),
    )


class ReportService:
    def __init__(self, db: AsyncSession, *, store_id: str | None):
        self.db = db
        # Tienda que acota TODAS las consultas del reporte: defensa en
        # profundidad sobre RLS (CLAUDE.md §2), la unica capa que la suite en
        # SQLite puede ejercitar. None solo para el superadmin, mismo criterio
        # que la politica RLS (ver core.roles.store_scope_for). Es parametro
        # obligatorio a proposito: un caller que lo olvide falla al construir,
        # no devuelve datos de otras tiendas en silencio.
        self.store_id = store_id

    def _store_scope(
        self, column: InstrumentedAttribute[str]
    ) -> list[ColumnElement[bool]]:
        """Predicado ``store_id`` para desempacar en el ``where`` de cada query."""
        if self.store_id is None:
            return []
        return [column == self.store_id]

    def _resolve_date_range(
        self, from_date: date | None, to_date: date | None
    ) -> tuple[date, date]:
        today = today_local()
        resolved_to = to_date or today
        resolved_from = from_date or (resolved_to - timedelta(days=30))

        if resolved_from > resolved_to:
            raise ValueError("from_date no puede ser mayor a to_date")

        # Cota del rango: un reporte de anios agrega y serializa sin techo. El
        # limite estaba definido en config pero no se aplicaba (codigo muerto).
        if (resolved_to - resolved_from).days > settings.REPORT_MAX_RANGE_DAYS:
            raise ValueError(
                "El rango del reporte no puede superar "
                f"{settings.REPORT_MAX_RANGE_DAYS} dias"
            )

        return resolved_from, resolved_to

    def _range_bounds(
        self, from_date: date, to_date: date
    ) -> tuple[datetime, datetime]:
        """[medianoche argentina de from_date, medianoche argentina del dia
        siguiente a to_date), como instantes UTC aware (regla 24).

        Antes era medianoche naive, o sea UTC = 21:00 hora local del dia
        anterior: los turnos de la noche caian en el reporte del dia siguiente.
        """
        start_dt = local_day_start(from_date)
        end_dt = local_day_start(to_date + timedelta(days=1))
        return start_dt, end_dt

    def _empty_debt_summary(self) -> ReportDebtSummary:
        return ReportDebtSummary(
            outstanding_balance=0.0,
            debtors_count=0,
            average_debt=0.0,
            top_debtors=[],
        )

    async def _build_debt_summary(self) -> ReportDebtSummary:
        # Solo el ultimo movimiento por cliente, resuelto en la DB (row_number
        # sobre la particion por client_id) en vez de traer todo el ledger y
        # deduplicar en Python: ese barrido crecia sin techo por cada cargo.
        ultimo_por_cliente = (
            select(
                CustomerLedger.id.label("id"),
                func.row_number()
                .over(
                    partition_by=CustomerLedger.client_id,
                    order_by=CustomerLedger.created_at.desc(),
                )
                .label("rn"),
            )
            .where(*self._store_scope(CustomerLedger.store_id))
            .subquery()
        )
        # Regla 11: el filtro "debe algo", el total, el conteo y el top-5 se
        # resuelven en la base. Al proceso vuelven dos escalares y cinco filas,
        # no una fila por deudor de la tienda.
        deudores = (
            select(
                CustomerLedger.client_id.label("client_id"),
                CustomerLedger.balance_after.label("balance"),
                CustomerLedger.created_at.label("created_at"),
            )
            .join(ultimo_por_cliente, CustomerLedger.id == ultimo_por_cliente.c.id)
            .where(
                ultimo_por_cliente.c.rn == 1,
                CustomerLedger.balance_after > 0,
                *self._store_scope(CustomerLedger.store_id),
            )
            .subquery()
        )
        totales = await self.db.execute(
            select(
                func.count(deudores.c.client_id),
                func.coalesce(func.sum(deudores.c.balance), 0),
            )
        )
        debtors_count, total_raw = totales.one()
        if not debtors_count:
            return self._empty_debt_summary()
        total_balance = Decimal(str(total_raw or 0))

        top_result = await self.db.execute(
            select(deudores.c.client_id, deudores.c.balance, User)
            .outerjoin(
                User,
                and_(
                    User.id == deudores.c.client_id,
                    *self._store_scope(User.store_id),
                ),
            )
            .order_by(deudores.c.balance.desc(), deudores.c.created_at.desc())
            .limit(5)
        )
        top_debtor_items = [
            ReportDebtClientItem(
                client_id=client_id or "",
                # Misma regla que top_clients y el panel (B5-18): nunca el
                # telefono, que antes aparecia como nombre del deudor.
                client_name=_report_client_name(user) or client_id or "Cliente",
                balance=round(float(Decimal(str(balance or 0))), 2),
            )
            for client_id, balance, user in top_result.all()
        ]

        return ReportDebtSummary(
            outstanding_balance=round(float(total_balance), 2),
            debtors_count=int(debtors_count),
            average_debt=round(float(total_balance / int(debtors_count)), 2),
            top_debtors=top_debtor_items,
        )

    def _select_in_range(
        self,
        *columns: Any,
        start_dt: datetime,
        end_dt: datetime,
        staff_id: str | None,
    ) -> Select[Any]:
        """Base comun de toda consulta sobre los turnos del rango.

        El listado y las agregaciones usan los mismos joins y filtros, asi el
        ingreso total, los top-5 y la lista de turnos hablan del mismo conjunto
        de filas: turnos con servicio, profesional y cliente, dentro del rango,
        de la tienda y, si corresponde, del profesional.
        """
        query = (
            select(*columns)
            .select_from(Appointment)
            .join(Service, Appointment.service_id == Service.id)
            .join(Staff, Appointment.staff_id == Staff.id)
            .join(User, Appointment.client_id == User.id)
            .where(
                Appointment.starts_at >= start_dt,
                Appointment.starts_at < end_dt,
                *self._store_scope(Appointment.store_id),
            )
        )
        if staff_id:
            query = query.where(Appointment.staff_id == staff_id)
        return query

    async def _fetch_rows(
        self,
        *,
        from_date: date,
        to_date: date,
        staff_id: str | None = None,
    ) -> list[tuple[Appointment, Service, Staff, User]]:
        start_dt, end_dt = self._range_bounds(from_date, to_date)
        query = self._select_in_range(
            Appointment,
            Service,
            Staff,
            User,
            start_dt=start_dt,
            end_dt=end_dt,
            staff_id=staff_id,
        ).order_by(Appointment.starts_at.asc())
        result = await self.db.execute(query)
        return cast(
            list[tuple[Appointment, Service, Staff, User]],
            result.all(),
        )

    def _paid_by_appointment(self) -> Subquery:
        """Plata acreditada por turno, agregada en la base.

        ``GROUP BY appointment_id`` + ``SUM(amount)`` sobre los pagos aprobados
        o confirmados a mano, acotado a la tienda. Es el bloque que usan el
        ingreso total, los top-5 y el ingreso por profesional: al proceso nunca
        vuelve una fila por pago (regla 11; antes se sumaba en un defaultdict).
        """
        return (
            select(
                Payment.appointment_id.label("appointment_id"),
                func.sum(Payment.amount).label("paid"),
            )
            .where(
                Payment.status.in_(_ACCREDITED_PAYMENT_STATUSES),
                *self._store_scope(Payment.store_id),
            )
            .group_by(Payment.appointment_id)
            .subquery()
        )

    async def _accredited_revenue(
        self, *, start_dt: datetime, end_dt: datetime, staff_id: str | None
    ) -> Decimal:
        """Ingreso total del rango: un escalar, sumado en la base."""
        paid = self._paid_by_appointment()
        result = await self.db.execute(
            self._select_in_range(
                func.coalesce(func.sum(paid.c.paid), 0),
                start_dt=start_dt,
                end_dt=end_dt,
                staff_id=staff_id,
            ).join(paid, paid.c.appointment_id == Appointment.id)
        )
        return Decimal(str(result.scalar_one() or 0))

    async def _accredited_revenue_by_staff(
        self, *, start_dt: datetime, end_dt: datetime, staff_id: str | None
    ) -> dict[str, Decimal]:
        """Ingreso cobrado por profesional: una fila por staff, no por pago."""
        paid = self._paid_by_appointment()
        result = await self.db.execute(
            self._select_in_range(
                Appointment.staff_id,
                func.coalesce(func.sum(paid.c.paid), 0),
                start_dt=start_dt,
                end_dt=end_dt,
                staff_id=staff_id,
            )
            .join(paid, paid.c.appointment_id == Appointment.id)
            .group_by(Appointment.staff_id)
        )
        return {
            row_staff_id: Decimal(str(total or 0))
            for row_staff_id, total in result.all()
        }

    async def _top_services(
        self, *, start_dt: datetime, end_dt: datetime, staff_id: str | None
    ) -> list[ReportTopServiceItem]:
        """Top-5 de servicios por turnos e ingreso: GROUP BY + ORDER BY + LIMIT."""
        paid = self._paid_by_appointment()
        turnos = func.count(Appointment.id)
        completados = func.sum(
            case((Appointment.status == AppointmentStatus.COMPLETED.value, 1), else_=0)
        )
        ingreso = func.coalesce(func.sum(paid.c.paid), 0)
        result = await self.db.execute(
            self._select_in_range(
                Service.public_id,
                Service.name,
                turnos,
                completados,
                ingreso,
                start_dt=start_dt,
                end_dt=end_dt,
                staff_id=staff_id,
            )
            .outerjoin(paid, paid.c.appointment_id == Appointment.id)
            .where(Appointment.status.not_in(_EXCLUDED_FROM_TOPS))
            .group_by(Service.id, Service.public_id, Service.name)
            # Mismo desempate que el orden anterior en Python (estable sobre
            # turnos ascendentes): a igual conteo e ingreso, el visto primero.
            .order_by(
                turnos.desc(), ingreso.desc(), func.min(Appointment.starts_at).asc()
            )
            .limit(5)
        )
        return [
            ReportTopServiceItem(
                service_id=service_id,
                service_name=service_name,
                appointments=int(appointments),
                completed_appointments=int(completed or 0),
                revenue=round(float(Decimal(str(revenue or 0))), 2),
            )
            for service_id, service_name, appointments, completed, revenue in (
                result.all()
            )
        ]

    async def _top_clients(
        self, *, start_dt: datetime, end_dt: datetime, staff_id: str | None
    ) -> list[ReportTopClientItem]:
        """Top-5 de clientes por turnos e ingreso: GROUP BY + ORDER BY + LIMIT."""
        paid = self._paid_by_appointment()
        turnos = func.count(Appointment.id)
        completados = func.sum(
            case((Appointment.status == AppointmentStatus.COMPLETED.value, 1), else_=0)
        )
        ingreso = func.coalesce(func.sum(paid.c.paid), 0)
        result = await self.db.execute(
            self._select_in_range(
                Appointment.client_id,
                User.first_name,
                User.last_name,
                User.email,
                func.max(Appointment.client_name),
                turnos,
                completados,
                ingreso,
                start_dt=start_dt,
                end_dt=end_dt,
                staff_id=staff_id,
            )
            .outerjoin(paid, paid.c.appointment_id == Appointment.id)
            .where(Appointment.status.not_in(_EXCLUDED_FROM_TOPS))
            .group_by(
                Appointment.client_id, User.first_name, User.last_name, User.email
            )
            .order_by(
                turnos.desc(), ingreso.desc(), func.min(Appointment.starts_at).asc()
            )
            .limit(5)
        )
        items: list[ReportTopClientItem] = []
        for (
            client_id,
            first_name,
            last_name,
            email,
            snapshot_name,
            appointments,
            completed,
            revenue,
        ) in result.all():
            items.append(
                ReportTopClientItem(
                    client_id=client_id,
                    client_name=_client_name_from_columns(
                        first_name, last_name, email, snapshot_name
                    )
                    or client_id,
                    appointments=int(appointments),
                    completed_appointments=int(completed or 0),
                    revenue=round(float(Decimal(str(revenue or 0))), 2),
                )
            )
        return items

    async def _historical_clients(
        self, *, end_dt: datetime, staff_id: str | None
    ) -> list[Any]:
        """Primera visita y contacto de cada cliente hasta el fin del rango.

        Antes se traia TODO el historial de turnos de la tienda (sin cota
        inferior) para calcular cohortes en Python. Solo hace falta, por
        cliente, la PRIMERA visita (MIN(starts_at)) y sus datos de contacto: eso
        es una agregacion, asi que se resuelve en la DB y vuelven O(clientes)
        filas en vez de O(turnos) ("visto antes del rango" == min < inicio).
        """
        query = (
            select(
                Appointment.client_id,
                User.first_name,
                User.last_name,
                User.email,
                func.min(Appointment.starts_at),
            )
            .join(User, Appointment.client_id == User.id)
            .where(
                Appointment.client_id.is_not(None),
                Appointment.starts_at < end_dt,
                *self._store_scope(Appointment.store_id),
            )
            .group_by(
                Appointment.client_id, User.first_name, User.last_name, User.email
            )
        )
        if staff_id:
            query = query.where(Appointment.staff_id == staff_id)
        # Con GROUP BY cada cliente aparece una sola vez, asi que el orden no
        # importa (_client_cohorts usa setdefault sobre la primera visita).
        result = await self.db.execute(query)
        return list(result.all())

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
        # Regla 11: total, por servicio y por cliente se agregan en la base; al
        # proceso vuelven un escalar y cinco filas por dimension, no una fila
        # por pago ni un acumulador por cada turno del rango.
        total_revenue = await self._accredited_revenue(
            start_dt=start_dt, end_dt=end_dt, staff_id=staff_id
        )
        top_services = await self._top_services(
            start_dt=start_dt, end_dt=end_dt, staff_id=staff_id
        )
        top_clients = await self._top_clients(
            start_dt=start_dt, end_dt=end_dt, staff_id=staff_id
        )
        aggregation = self._aggregate_summary(
            rows=rows,
            historical_rows=await self._historical_clients(
                end_dt=end_dt, staff_id=staff_id
            ),
            start_dt=start_dt,
            end_dt=end_dt,
        )
        debt_summary = (
            self._empty_debt_summary() if staff_id else await self._build_debt_summary()
        )

        return ReportSummaryResponse(
            from_date=resolved_from,
            to_date=resolved_to,
            stats=_summary_stats(aggregation, total_revenue),
            client_stats=_client_stats(aggregation),
            top_services=top_services,
            top_clients=top_clients,
            debt_summary=debt_summary,
            appointments=aggregation.items,
        )

    def _aggregate_summary(
        self,
        *,
        rows: list[Any],
        historical_rows: list[Any],
        start_dt: datetime,
        end_dt: datetime,
    ) -> _SummaryAggregation:
        """Agrega los turnos del rango en metricas puras (sin tocar la base).

        Separado de get_summary para que la lógica de conteo/cohortes se pueda
        leer y testear sin montar queries: recibe lo ya traido y devuelve el
        resultado listo para envolver en DTOs. El dinero y los top-5 no pasan
        por aca: se agregan en SQL (regla 11).
        """
        cohorts = _client_cohorts(historical_rows, start_dt)
        known_client_names = cohorts.known_names
        items: list[ReportAppointmentItem] = []
        status_counts: dict[str, int] = defaultdict(int)
        clients_in_range: set[str] = set()

        for row in rows:
            appointment, service, staff, client = _unpack_row(row)
            client_id = appointment.client_id
            current_name = _report_client_name(client, appointment.client_name)
            if client_id:
                clients_in_range.add(client_id)
                if current_name:
                    known_client_names[client_id] = current_name
            counter = _STATUS_COUNTERS.get((appointment.status or "").upper())
            if counter:
                status_counts[counter] += 1
            resolved_client_name = (
                current_name or known_client_names.get(client_id or "", "") or "Cliente"
            )
            items.append(
                _appointment_item(appointment, service, staff, resolved_client_name)
            )

        new_clients = sum(
            1
            for client_id in clients_in_range
            if start_dt <= cohorts.first_seen.get(client_id, start_dt) < end_dt
        )
        return _SummaryAggregation(
            items=items,
            total_appointments=len(items),
            completed=status_counts["completed"],
            cancelled=status_counts["cancelled"],
            pending=status_counts["pending"],
            confirmed=status_counts["confirmed"],
            total_clients=len(clients_in_range),
            new_clients=new_clients,
            returning_clients=max(len(clients_in_range) - new_clients, 0),
            inactive_clients=len(cohorts.seen_before_range - clients_in_range),
        )

    async def _active_staff(self, only_staff_id: str | None) -> list[Staff]:
        query = select(Staff).where(
            Staff.is_active.is_(True), *self._store_scope(Staff.store_id)
        )
        if only_staff_id:
            query = query.where(Staff.id == only_staff_id)
        result = await self.db.execute(query.order_by(Staff.display_name.asc()))
        return list(result.scalars().all())

    async def _schedules_by_staff(
        self, staff_ids: list[str]
    ) -> dict[str, list[Schedule]]:
        result = await self.db.execute(
            select(Schedule).where(
                Schedule.staff_id.in_(staff_ids),
                *self._store_scope(Schedule.store_id),
            )
        )
        by_staff: dict[str, list[Schedule]] = defaultdict(list)
        for schedule in result.scalars().all():
            by_staff[schedule.staff_id].append(schedule)
        return by_staff

    async def _blocks_by_staff(
        self, staff_ids: list[str], *, start_dt: datetime, end_dt: datetime
    ) -> dict[str, list[StaffBlock]]:
        """Bloqueos activos que se superponen con el rango, por profesional."""
        result = await self.db.execute(
            select(StaffBlock).where(
                StaffBlock.staff_id.in_(staff_ids),
                StaffBlock.is_active.is_(True),
                StaffBlock.starts_at < end_dt,
                StaffBlock.ends_at > start_dt,
                *self._store_scope(StaffBlock.store_id),
            )
        )
        by_staff: dict[str, list[StaffBlock]] = defaultdict(list)
        for block in result.scalars().all():
            by_staff[block.staff_id].append(block)
        return by_staff

    async def get_professionals(
        self,
        from_date: date | None,
        to_date: date | None,
        *,
        only_staff_id: str | None = None,
    ) -> ProfessionalReportsResponse:
        resolved_from, resolved_to = self._resolve_date_range(from_date, to_date)
        start_dt, end_dt = self._range_bounds(resolved_from, resolved_to)

        staff_members = await self._active_staff(only_staff_id)
        staff_ids = [staff.id for staff in staff_members]
        if not staff_ids:
            return ProfessionalReportsResponse(
                from_date=resolved_from, to_date=resolved_to, professionals=[]
            )

        schedules_by_staff = await self._schedules_by_staff(staff_ids)
        blocks_by_staff = await self._blocks_by_staff(
            staff_ids, start_dt=start_dt, end_dt=end_dt
        )
        rows = await self._fetch_rows(
            from_date=resolved_from, to_date=resolved_to, staff_id=only_staff_id
        )
        appointments_by_staff: dict[str, list[Appointment]] = defaultdict(list)
        for row in rows:
            appointment, _, staff = row[:3]
            appointments_by_staff[staff.id].append(appointment)

        # Mismo criterio que el resumen: ingreso = plata acreditada, sumada
        # por profesional en la base (regla 11), no turno a turno en Python.
        revenue_by_staff = await self._accredited_revenue_by_staff(
            start_dt=start_dt, end_dt=end_dt, staff_id=only_staff_id
        )
        total_days = (resolved_to - resolved_from).days + 1
        items = [
            _professional_item(
                staff,
                appointments_by_staff.get(staff.id, []),
                available_minutes=_available_minutes(
                    schedules_by_staff.get(staff.id, []), resolved_from, total_days
                ),
                blocked_minutes=_blocked_minutes(
                    blocks_by_staff.get(staff.id, []), start_dt, end_dt
                ),
                revenue=float(revenue_by_staff.get(staff.id, Decimal("0.00"))),
            )
            for staff in staff_members
        ]
        return ProfessionalReportsResponse(
            from_date=resolved_from,
            to_date=resolved_to,
            professionals=items,
        )

    async def get_trend(
        self,
        *,
        months: int = 6,
        staff_id: str | None = None,
    ) -> ReportTrendResponse:
        """Serie mensual de turnos (total / completados / cancelados).

        Agrupa por mes calendario ARGENTINO en la base (GROUP BY, no en
        Python) y rellena con ceros los meses sin turnos para que el grafico
        de barras del dashboard no tenga huecos.
        """
        if months < 1:
            raise ValueError("months debe ser mayor a 0")

        today = today_local()
        current_month_start = date(today.year, today.month, 1)
        start_month = _add_months(current_month_start, -(months - 1))
        # months + 1 limites: el ultimo es el inicio del mes siguiente, para
        # cubrir el mes actual completo (no solo hasta "hoy"): un turno futuro
        # ya agendado dentro del mes en curso tiene que contar en su bucket.
        month_starts = [_add_months(start_month, i) for i in range(months + 1)]
        bounds = [local_day_start(month) for month in month_starts]

        month_key = _local_month_key(month_starts, bounds).label("month")
        in_range = select(month_key, Appointment.status.label("status")).where(
            Appointment.starts_at >= bounds[0],
            Appointment.starts_at < bounds[-1],
            *self._store_scope(Appointment.store_id),
        )
        if staff_id:
            in_range = in_range.where(Appointment.staff_id == staff_id)
        rows = in_range.subquery()
        result = await self.db.execute(
            select(rows.c.month, rows.c.status, func.count()).group_by(
                rows.c.month, rows.c.status
            )
        )

        buckets: dict[str, MetricBucket] = {}
        cursor = start_month
        for _ in range(months):
            buckets[cursor.strftime("%Y-%m")] = {
                "total": 0,
                "completed": 0,
                "cancelled": 0,
            }
            cursor = _add_months(cursor, 1)

        for key, status, count in result.all():
            bucket = buckets.setdefault(
                key, {"total": 0, "completed": 0, "cancelled": 0}
            )
            bucket["total"] += count
            if status == AppointmentStatus.COMPLETED.value:
                bucket["completed"] += count
            elif status == AppointmentStatus.CANCELLED.value:
                bucket["cancelled"] += count

        points = [
            ReportTrendPoint(
                month=key,
                total_appointments=buckets[key]["total"],
                completed_appointments=buckets[key]["completed"],
                cancelled_appointments=buckets[key]["cancelled"],
            )
            for key in sorted(buckets.keys())
        ]
        return ReportTrendResponse(points=points)
