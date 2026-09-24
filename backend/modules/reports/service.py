from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, NamedTuple, cast

from sqlalchemy import ColumnElement, Exists, Select, and_, case, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, aliased

from core.config import settings
from core.utils import ensure_utc_aware, local_day_start, today_local

from modules.appointments.model import Appointment, AppointmentStatus
from modules.appointments.repository import active_block_overlap
from modules.audit.repository import AuditRepository
from modules.ledger.model import CustomerLedger
from modules.payments.model import Payment, PaymentStatus
from modules.reports.schemas import (
    AuditLogItem,
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

# Tope de turnos de un export (F1-07, decision 19 del dueno). El archivo se
# arma entero en memoria del proceso de la API; por encima de esto se pide
# acotar el rango (422) en vez de congelar un worker. El job asincrono queda
# para mas adelante.
EXPORT_MAX_ROWS = 20_000


class ExportTooLargeError(Exception):
    """El rango pedido tiene mas turnos que ``EXPORT_MAX_ROWS``."""

    def __init__(self, max_rows: int) -> None:
        self.max_rows = max_rows
        super().__init__(f"El export supera {max_rows} turnos")


# Lo que el archivo no escribe (cohortes, top-5, deuda) no se calcula para el
# export: el resumen viaja con estos vacios.
_EXPORT_EMPTY_CLIENT_STATS = ReportClientStats(
    total_clients=0, new_clients=0, returning_clients=0, inactive_clients=0
)

# Recursos cuya auditoria expone el panel (B5-12): los que escribe
# AuditRepository.log desde appointments y appointment_blocks. Las acciones
# del superadmin sobre la tienda (Store, User, suscripciones) quedan afuera.
AUDITED_SCHEDULE_RESOURCES = ("Appointment", "AppointmentBlock")

# Un pago cuenta como ingreso solo si esta acreditado (Mercado Pago aprobado o
# cobro manual confirmado). Unica definicion de la regla para reportes y panel
# (B5-10): modules/dashboard/repository.py la importa de aca. Un pago
# reembolsado pasa a ``refunded`` y deja de contar.
ACCREDITED_PAYMENT_STATUSES = [
    PaymentStatus.APPROVED.value,
    PaymentStatus.MANUAL_CONFIRMED.value,
]
# Turnos que NO se prestaron. Su plata acreditada es sena retenida, no ingreso
# por servicio, asi que quedan fuera de los top-5 y entran en
# retained_deposit_revenue. Las dos mitades usan el MISMO conjunto para que
# sean complementarias: ingreso por servicio == total_revenue - retenido
# (AUD2-B5-06). El ausente pago la sena y no vino —el caso por el que existe
# la sena—; el vencido con pago acreditado es la carrera entre el expirador y
# el webhook aprobado.
_NOT_SERVED_STATUSES = [
    AppointmentStatus.CANCELLED.value,
    AppointmentStatus.ABSENT.value,
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


class _AccreditedRevenue(NamedTuple):
    """Plata acreditada del rango y turnos que la generaron.

    Las dos mitades del ticket promedio salen de la misma consulta para que
    nunca hablen de conjuntos distintos.
    """

    total: Decimal
    appointments: int


# Estado del turno (en mayusculas) -> contador del resumen. Estan los SIETE
# estados del grafo, asi que los contadores suman total_appointments
# (AUD2-B5-14: antes absent y expired solo entraban en el total y los numeros
# de la pantalla no cerraban). pending_payment cuenta como pendiente: para el
# dueno es el mismo casillero.
_STATUS_COUNTERS = {
    "COMPLETED": "completed",
    "CANCELLED": "cancelled",
    "PENDING": "pending",
    "PENDING_PAYMENT": "pending",
    "CONFIRMED": "confirmed",
    "ABSENT": "absent",
    "EXPIRED": "expired",
}
# Contador -> estados que suma, como los guarda la base (en minusculas, por
# ``check_appointment_status_v3``). Lo usa el agregado condicional del resumen.
_COUNTER_STATUSES: dict[str, list[str]] = {
    contador: [
        estado.lower() for estado, suyo in _STATUS_COUNTERS.items() if suyo == contador
    ]
    for contador in dict.fromkeys(_STATUS_COUNTERS.values())
}


class _RangeTotals(NamedTuple):
    """Conteo por estado, ingreso acreditado y sena retenida del rango."""

    counts: dict[str, int]
    cobrado: _AccreditedRevenue
    retained: Decimal


class _StaffTotals(NamedTuple):
    """Lo que el reporte por profesional necesita de sus turnos del rango."""

    appointments: int
    completed: int
    confirmed: int
    absent: int
    cancelled: int
    used_minutes: int
    revenue: Decimal


_EMPTY_STAFF_TOTALS = _StaffTotals(0, 0, 0, 0, 0, 0, Decimal("0.00"))


def _appointment_item(
    appointment: Appointment, service: Service, staff_name: str, client_name: str
) -> ReportAppointmentItem:
    return ReportAppointmentItem(
        public_id=appointment.public_id,
        starts_at=appointment.starts_at,
        ends_at=appointment.ends_at,
        status=appointment.status,
        service_name=service.name,
        staff_name=staff_name,
        client_name=client_name,
        # Precio del turno: el congelado al reservar; si es un turno viejo sin
        # snapshot, el precio de lista actual.
        service_price=float(
            appointment.price_amount
            if appointment.price_amount is not None
            else service.price
        ),
    )


def _export_item(fila: Any) -> ReportAppointmentItem:
    """Fila de columnas del export -> item, con las reglas de ``_appointment_item``.

    El nombre sigue a ``_report_client_name`` (el ``full_name`` del modelo une
    nombre y apellido sin blancos sobrantes; si no hay, el email; si no, el
    snapshot del turno) y el precio es el congelado o, en un turno viejo, el
    de lista.
    """
    (
        public_id,
        starts_at,
        ends_at,
        status,
        price_amount,
        snapshot,
        service_name,
        service_price,
        staff_name,
        first_name,
        last_name,
        email,
    ) = fila
    full_name = " ".join(
        part.strip() for part in (first_name, last_name) if part and part.strip()
    )
    return ReportAppointmentItem(
        public_id=public_id,
        starts_at=starts_at,
        ends_at=ends_at,
        status=status,
        service_name=service_name,
        staff_name=staff_name,
        client_name=full_name or email or (snapshot or "").strip() or "Cliente",
        service_price=float(
            price_amount if price_amount is not None else service_price
        ),
    )


def _summary_stats(
    counts: dict[str, int],
    cobrado: _AccreditedRevenue,
    retained_deposit_revenue: Decimal,
) -> ReportSummaryStats:
    """Metricas del resumen a partir del conteo por estado que devuelve la base.

    El ticket promedio divide la plata acreditada por los turnos que la
    generaron, no por los turnos agendados (AUD2-B5-04).
    """
    revenue = float(cobrado.total)
    return ReportSummaryStats(
        total_appointments=counts.get("total", 0),
        completed_appointments=counts.get("completed", 0),
        cancelled_appointments=counts.get("cancelled", 0),
        pending_appointments=counts.get("pending", 0),
        confirmed_appointments=counts.get("confirmed", 0),
        absent_appointments=counts.get("absent", 0),
        expired_appointments=counts.get("expired", 0),
        total_revenue=round(revenue, 2),
        average_ticket=(
            round(revenue / cobrado.appointments, 2) if cobrado.appointments else 0.0
        ),
        retained_deposit_revenue=round(float(retained_deposit_revenue), 2),
    )


def _weekday_count(from_date: date, total_days: int, weekday: int) -> int:
    """Cuantas fechas de ``[from_date, from_date + total_days)`` caen en ``weekday``.

    Aritmetica de calendario (B5-20): cada semana completa aporta una, y el
    resto de ``total_days % 7`` dias aporta otra si ``weekday`` esta entre los
    primeros dias de la semana parcial, contados desde ``from_date``. Antes se
    recorria el rango fecha por fecha por cada horario de cada profesional.
    """
    full_weeks, remainder = divmod(total_days, 7)
    offset = (weekday - from_date.weekday()) % 7
    return full_weeks + (1 if offset < remainder else 0)


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
        matching_days = _weekday_count(from_date, total_days, schedule.day_of_week)
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


# Turnos que no ocupan agenda: no suman ``used_minutes`` del profesional.
_NOT_USING_TIME = [
    AppointmentStatus.CANCELLED.value,
    AppointmentStatus.EXPIRED.value,
]


def _professional_item(
    staff_id: str,
    staff_name: str,
    totals: _StaffTotals,
    *,
    available_minutes: int,
    blocked_minutes: int,
) -> ProfessionalReportItem:
    used_minutes = totals.used_minutes
    effective_minutes = max(available_minutes - blocked_minutes, 0)
    occupancy_rate = (
        round((used_minutes / effective_minutes) * 100, 2) if effective_minutes else 0.0
    )
    return ProfessionalReportItem(
        staff_id=staff_id,
        staff_name=staff_name,
        appointments=totals.appointments,
        completed_appointments=totals.completed,
        confirmed_appointments=totals.confirmed,
        absent_appointments=totals.absent,
        cancelled_appointments=totals.cancelled,
        used_minutes=used_minutes,
        used_hours=round(used_minutes / 60, 2),
        available_minutes=available_minutes,
        available_hours=round(available_minutes / 60, 2),
        blocked_minutes=blocked_minutes,
        blocked_hours=round(blocked_minutes / 60, 2),
        occupancy_rate=occupancy_rate,
        revenue=round(float(totals.revenue), 2),
    )


class ReportService:
    def __init__(self, db: AsyncSession, *, store_id: str):
        self.db = db
        # Tienda que acota TODAS las consultas del reporte: defensa en
        # profundidad sobre RLS (CLAUDE.md §2), la unica capa que la suite en
        # SQLite puede ejercitar. Tambien para el superadmin, cuya sesion abre
        # RLS (B5-02; ver core.roles.store_scope_for). Es parametro obligatorio
        # y nunca None a proposito: un caller que lo olvide falla al construir,
        # no devuelve datos de otras tiendas en silencio.
        self.store_id = store_id

    def _store_scope(
        self, column: InstrumentedAttribute[str]
    ) -> list[ColumnElement[bool]]:
        """Predicado ``store_id`` para desempacar en el ``where`` de cada query."""
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
        join_entities: bool = True,
    ) -> Select[Any]:
        """Base comun de toda consulta sobre los turnos del rango.

        El listado y las agregaciones usan los mismos filtros, asi el ingreso
        total, los top-5 y la lista de turnos hablan del mismo conjunto de
        filas: turnos con servicio, profesional y cliente, dentro del rango,
        de la tienda y, si corresponde, del profesional.

        ``join_entities=False`` (F3-04) es para los agregados que no leen
        columnas de ``services`` ni ``staff``: esos dos joins no cambian el
        conjunto de filas (``service_id`` y ``staff_id`` son FK NOT NULL y la
        baja de un servicio o profesional es logica, ``is_active``), asi que
        se ahorran. El join a ``users`` se conserva SIEMPRE: ``client_id`` es
        nullable y un turno sin cliente vinculado nunca entro al reporte;
        sacarlo cambiaria los totales
        (``test_los_agregados_sin_joins_hablan_del_mismo_conjunto_de_filas``).
        """
        query = select(*columns).select_from(Appointment)
        if join_entities:
            query = query.join(Service, Appointment.service_id == Service.id).join(
                Staff, Appointment.staff_id == Staff.id
            )
        query = query.join(User, Appointment.client_id == User.id).where(
            Appointment.starts_at >= start_dt,
            Appointment.starts_at < end_dt,
            *self._store_scope(Appointment.store_id),
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
        page: slice | None = None,
    ) -> list[tuple[Appointment, Service, str, User]]:
        """Turnos del rango para el detalle. ``page`` acota EN SQL.

        AUD2-B5-02: antes traia el rango entero (hasta ~14.800 tuplas de cuatro
        entidades ORM con el tope de 370 dias) y la pagina se recortaba en
        Python. ``None`` = sin tope.

        Del profesional viaja solo ``display_name`` (F3-04): cargar ``Staff``
        como entidad disparaba sus relaciones (dos sentencias mas por pagina).
        """
        start_dt, end_dt = self._range_bounds(from_date, to_date)
        query = self._select_in_range(
            Appointment,
            Service,
            Staff.display_name,
            User,
            start_dt=start_dt,
            end_dt=end_dt,
            staff_id=staff_id,
            # Desempate por id: el orden tiene que ser estable para que las paginas
            # del detalle (B5-15) no repitan ni salteen turnos a la misma hora.
        ).order_by(Appointment.starts_at.asc(), Appointment.id.asc())
        if page is not None:
            offset = page.start or 0
            query = query.offset(offset).limit(page.stop - offset)
        result = await self.db.execute(query)
        return cast(
            list[tuple[Appointment, Service, str, User]],
            result.all(),
        )

    def _accredited_payment_join(self) -> ColumnElement[bool]:
        """Condicion de join a ``payments``: el pago acreditado de ese turno.

        AUD2-B5-08: antes esto era una subconsulta ``GROUP BY appointment_id``
        sobre TODOS los pagos de la tienda, sin cota de fecha, construida de
        nuevo en cada una de las cuatro consultas de plata del resumen.
        Postgres no puede empujar el predicado de rango adentro de ese
        ``GROUP BY``, asi que el agregado se materializaba entero y el reporte
        de "los ultimos 7 dias" se volvia mas lento cada mes aunque el rango no
        cambiara. ``uq_payments_store_appointment`` garantiza a lo sumo UN pago
        por turno y por tienda, asi que el ``SUM`` no aportaba nada que el join
        directo no de: ahora el predicado de rango queda del lado de
        ``appointments`` y el plan usa el indice de ``appointment_id``.
        El ``store_id`` va igual, por defensa en profundidad (CLAUDE.md §2).
        """
        return and_(
            Payment.appointment_id == Appointment.id,
            Payment.status.in_(ACCREDITED_PAYMENT_STATUSES),
            *self._store_scope(Payment.store_id),
        )

    async def _range_totals(
        self, *, start_dt: datetime, end_dt: datetime, staff_id: str | None
    ) -> _RangeTotals:
        """Conteo por estado, ingreso acreditado y sena retenida: UNA sentencia.

        F3-04 (R2-03): eran tres consultas sobre el mismo conjunto de filas
        (``GROUP BY status``, suma acreditada con su conteo y suma de los no
        prestados). Ahora es una fila con agregados condicionales, todo sumado
        en la base (regla 11):

        - Contadores: los SIETE estados del grafo caen en ``_COUNTER_STATUSES``,
          asi que suman ``total_appointments`` (AUD2-B5-14).
        - Ingreso y turnos cobrados: el ticket promedio divide la plata por los
          turnos que la generaron, no por los agendados (AUD2-B5-04). El
          ``LEFT JOIN`` deja ``NULL`` donde no hay pago acreditado, que
          ``SUM`` y ``COUNT(payments.id)`` ignoran; a lo sumo hay un pago por
          turno (``uq_payments_store_appointment``), asi que no se duplican
          turnos.
        - Sena retenida: plata acreditada de turnos que NO se prestaron
          (B5-10, AUD2-B5-06), la mitad complementaria de los top-5, que
          excluyen exactamente esos estados.

        Sin joins a ``services`` ni ``staff``: no leen sus columnas
        (``join_entities=False``).
        """
        cobrado = func.coalesce(func.sum(Payment.amount), 0)
        contadores = [
            func.count(Appointment.id).filter(Appointment.status.in_(estados))
            for estados in _COUNTER_STATUSES.values()
        ]
        result = await self.db.execute(
            self._select_in_range(
                func.count(Appointment.id),
                *contadores,
                cobrado,
                func.count(Payment.id),
                func.coalesce(
                    func.sum(Payment.amount).filter(
                        Appointment.status.in_(_NOT_SERVED_STATUSES)
                    ),
                    0,
                ),
                start_dt=start_dt,
                end_dt=end_dt,
                staff_id=staff_id,
                join_entities=False,
            ).outerjoin(Payment, self._accredited_payment_join())
        )
        total, *por_contador, plata, cobrados, retenido = result.one()
        counts = {"total": int(total or 0)}
        for contador, cantidad in zip(_COUNTER_STATUSES, por_contador):
            counts[contador] = int(cantidad or 0)
        return _RangeTotals(
            counts=counts,
            cobrado=_AccreditedRevenue(Decimal(str(plata or 0)), int(cobrados or 0)),
            retained=Decimal(str(retenido or 0)),
        )

    async def _staff_totals(
        self, *, start_dt: datetime, end_dt: datetime, staff_id: str | None
    ) -> dict[str, _StaffTotals]:
        """Por profesional: turnos por estado, minutos usados e ingreso cobrado.

        F3-04 (R2-03): antes se traia UNA FILA POR TURNO del rango como cuatro
        entidades ORM para contar y sumar en Python, y el ingreso iba en otra
        consulta. Ahora es ``GROUP BY staff_id`` con agregados condicionales:
        una fila por profesional, la plata sumada en la base (regla 11). Los
        minutos salen del snapshot del turno (AUD2-B5-10) y no cuentan los
        cancelados ni los vencidos, que no ocupan agenda.
        """
        estado = Appointment.status

        def contar(valor: AppointmentStatus) -> Any:
            return func.count(Appointment.id).filter(estado == valor.value)

        result = await self.db.execute(
            self._select_in_range(
                Appointment.staff_id,
                func.count(Appointment.id),
                contar(AppointmentStatus.COMPLETED),
                contar(AppointmentStatus.CONFIRMED),
                contar(AppointmentStatus.ABSENT),
                contar(AppointmentStatus.CANCELLED),
                func.coalesce(
                    func.sum(Appointment.duration_minutes).filter(
                        estado.not_in(_NOT_USING_TIME)
                    ),
                    0,
                ),
                func.coalesce(func.sum(Payment.amount), 0),
                start_dt=start_dt,
                end_dt=end_dt,
                staff_id=staff_id,
                join_entities=False,
            )
            .outerjoin(Payment, self._accredited_payment_join())
            .group_by(Appointment.staff_id)
        )
        return {
            fila_staff: _StaffTotals(
                appointments=int(turnos or 0),
                completed=int(completados or 0),
                confirmed=int(confirmados or 0),
                absent=int(ausentes or 0),
                cancelled=int(cancelados or 0),
                used_minutes=int(minutos or 0),
                revenue=Decimal(str(plata or 0)),
            )
            for (
                fila_staff,
                turnos,
                completados,
                confirmados,
                ausentes,
                cancelados,
                minutos,
                plata,
            ) in result.all()
        }

    async def _top_services(
        self, *, start_dt: datetime, end_dt: datetime, staff_id: str | None
    ) -> list[ReportTopServiceItem]:
        """Top-5 de servicios por turnos e ingreso: GROUP BY + ORDER BY + LIMIT.

        Es un RANKING, no la definicion del ingreso por servicio: con mas de
        cinco servicios en el rango su suma es menor que
        ``total_revenue - retained_deposit_revenue``, que es donde vive esa
        identidad (AUD2-B5-05).
        """
        turnos = func.count(Appointment.id)
        completados = func.sum(
            case((Appointment.status == AppointmentStatus.COMPLETED.value, 1), else_=0)
        )
        ingreso = func.coalesce(func.sum(Payment.amount), 0)
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
            .outerjoin(Payment, self._accredited_payment_join())
            .where(Appointment.status.not_in(_NOT_SERVED_STATUSES))
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
        turnos = func.count(Appointment.id)
        completados = func.sum(
            case((Appointment.status == AppointmentStatus.COMPLETED.value, 1), else_=0)
        )
        ingreso = func.coalesce(func.sum(Payment.amount), 0)
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
            .outerjoin(Payment, self._accredited_payment_join())
            .where(Appointment.status.not_in(_NOT_SERVED_STATUSES))
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

    def _visited_before(
        self, client_id: Any, *, start_dt: datetime, staff_id: str | None
    ) -> Exists:
        """``EXISTS`` un turno del cliente en la tienda anterior al rango.

        Correlacionado por ``client_id`` (``ix_appointments_client_id``): cada
        sonda recorre los turnos de UN cliente y se detiene en el primero que
        cumple, no la historia de la tienda. Con el mismo filtro de profesional
        que el rango, como la cohorte de siempre.
        """
        previo = aliased(Appointment, name="previo")
        condiciones = [
            previo.client_id == client_id,
            previo.starts_at < start_dt,
            previo.store_id == self.store_id,
        ]
        if staff_id:
            condiciones.append(previo.staff_id == staff_id)
        return exists().where(*condiciones)

    async def _client_cohorts(
        self, *, start_dt: datetime, end_dt: datetime, staff_id: str | None
    ) -> ReportClientStats:
        """Cohortes de clientes del rango, con costo proporcional al rango.

        F3-05 (R2-06): antes se agrupaba por cliente TODA la historia de la
        tienda anterior al fin del rango (``starts_at < fin``, sin cota
        inferior) para saber la primera visita de cada uno; el reporte de 7
        dias del Dashboard se volvia mas lento cada mes. Ahora, en una
        sentencia:

        - Clientes del rango: ``DISTINCT client_id`` de los turnos del rango
          (indice ``(store_id, starts_at)``), como CTE.
        - Nuevos: los del rango sin un turno anterior (``NOT EXISTS``).
        - Inactivos = vinieron antes y no en el rango. Se cuentan como los
          clientes de la tienda con ALGUN turno anterior (``EXISTS``, que se
          detiene en el primero) menos los recurrentes (del rango y con turno
          anterior): la diferencia de conjuntos es exactamente la definicion,
          y evita recorrer la historia de cada inactivo buscando un turno en
          el rango que no tiene.

        Mismo conjunto que antes: turnos de cualquier estado, con cliente
        vinculado (join a ``users``), de la tienda y, si corresponde, del
        profesional (``test_reportes_cohortes_acotadas.py`` lo compara contra
        la consulta vieja).
        """
        del_rango = (
            select(Appointment.client_id.label("client_id"))
            .join(User, Appointment.client_id == User.id)
            .where(
                Appointment.client_id.is_not(None),
                Appointment.starts_at >= start_dt,
                Appointment.starts_at < end_dt,
                *self._store_scope(Appointment.store_id),
            )
            .distinct()
        )
        if staff_id:
            del_rango = del_rango.where(Appointment.staff_id == staff_id)
        clientes = del_rango.cte("clientes_del_rango")
        antes: dict[str, Any] = {"start_dt": start_dt, "staff_id": staff_id}
        total = select(func.count()).select_from(clientes).scalar_subquery()
        nuevos = (
            select(func.count())
            .select_from(clientes)
            .where(~self._visited_before(clientes.c.client_id, **antes))
            .scalar_subquery()
        )
        con_historia = (
            select(func.count(User.id))
            .where(
                *self._store_scope(User.store_id),
                self._visited_before(User.id, **antes),
            )
            .scalar_subquery()
        )
        result = await self.db.execute(select(total, nuevos, con_historia))
        total_n, nuevos_n, historia_n = (int(valor or 0) for valor in result.one())
        recurrentes = max(total_n - nuevos_n, 0)
        return ReportClientStats(
            total_clients=total_n,
            new_clients=nuevos_n,
            returning_clients=recurrentes,
            inactive_clients=max(historia_n - recurrentes, 0),
        )

    async def get_summary(
        self,
        from_date: date | None,
        to_date: date | None,
        *,
        staff_id: str | None = None,
        page: slice | None = None,
    ) -> ReportSummaryResponse:
        """``page`` acota el detalle ``appointments`` EN SQL (AUD2-B5-02).

        Los totales, las cohortes y los top-5 son siempre del rango completo y
        se agregan en la base (regla 11): ninguna consulta trae una fila por
        turno. ``page`` en ``None`` devuelve el detalle entero (el export).
        """
        resolved_from, resolved_to = self._resolve_date_range(from_date, to_date)
        start_dt, end_dt = self._range_bounds(resolved_from, resolved_to)
        rango: dict[str, Any] = {
            "start_dt": start_dt,
            "end_dt": end_dt,
            "staff_id": staff_id,
        }
        # Ingreso = plata efectivamente cobrada, no turnos agendados. La fuente
        # de verdad es el pago acreditado (Mercado Pago aprobado, o cobro manual
        # que el dueno confirma por efectivo/WhatsApp). Un turno confirmado pero
        # sin pago acreditado es una reserva, no un ingreso. El monto ya viene
        # con el descuento de la promo aplicado y al precio historico, asi que
        # esto tambien resuelve el precio de lista y las promociones.
        totales = await self._range_totals(**rango)
        top_services = await self._top_services(**rango)
        top_clients = await self._top_clients(**rango)
        client_stats = await self._client_cohorts(**rango)
        debt_summary = (
            self._empty_debt_summary() if staff_id else await self._build_debt_summary()
        )
        rows = await self._fetch_rows(
            from_date=resolved_from,
            to_date=resolved_to,
            staff_id=staff_id,
            page=page,
        )
        items = [
            _appointment_item(
                appointment,
                service,
                staff_name,
                _report_client_name(client, appointment.client_name) or "Cliente",
            )
            for appointment, service, staff_name, client in rows
        ]
        offset = (page.start or 0) if page is not None else 0

        return ReportSummaryResponse(
            from_date=resolved_from,
            to_date=resolved_to,
            stats=_summary_stats(totales.counts, totales.cobrado, totales.retained),
            client_stats=client_stats,
            top_services=top_services,
            top_clients=top_clients,
            debt_summary=debt_summary,
            appointments=items,
            # AUD2-B5-01: el corte tiene que ser visible; con esto y
            # stats.total_appointments el panel puede mostrar "N de M".
            has_more=offset + len(items) < totales.counts.get("total", 0),
        )

    async def get_export_rows(
        self,
        from_date: date | None,
        to_date: date | None,
        *,
        staff_id: str | None = None,
    ) -> ReportSummaryResponse:
        """Lo que escribe el archivo de export, y nada mas (F1-07, R2-02).

        Mismo rango, mismos filtros y mismas metricas del encabezado que
        ``get_summary``; sin top-5, cohortes ni deuda (el archivo no los
        escribe) y con el detalle leido por columnas, no como cuatro entidades
        ORM por turno. Los totales van primero (una sentencia, F3-04): si el
        rango pasa de ``EXPORT_MAX_ROWS`` se corta antes de traer una sola fila.
        """
        resolved_from, resolved_to = self._resolve_date_range(from_date, to_date)
        start_dt, end_dt = self._range_bounds(resolved_from, resolved_to)
        rango: dict[str, Any] = {
            "start_dt": start_dt,
            "end_dt": end_dt,
            "staff_id": staff_id,
        }
        totales = await self._range_totals(**rango)
        if totales.counts.get("total", 0) > EXPORT_MAX_ROWS:
            raise ExportTooLargeError(EXPORT_MAX_ROWS)
        return ReportSummaryResponse(
            from_date=resolved_from,
            to_date=resolved_to,
            stats=_summary_stats(totales.counts, totales.cobrado, totales.retained),
            client_stats=_EXPORT_EMPTY_CLIENT_STATS,
            debt_summary=self._empty_debt_summary(),
            appointments=await self._fetch_export_items(**rango),
        )

    async def _fetch_export_items(
        self, *, start_dt: datetime, end_dt: datetime, staff_id: str | None
    ) -> list[ReportAppointmentItem]:
        """El detalle del export por columnas, en el orden estable del detalle."""
        result = await self.db.execute(
            self._select_in_range(
                Appointment.id,
                Appointment.starts_at,
                Appointment.ends_at,
                Appointment.status,
                Appointment.price_amount,
                Appointment.client_name,
                Service.name,
                Service.price,
                Staff.display_name,
                User.first_name,
                User.last_name,
                User.email,
                start_dt=start_dt,
                end_dt=end_dt,
                staff_id=staff_id,
            ).order_by(Appointment.starts_at.asc(), Appointment.id.asc())
        )
        return [_export_item(fila) for fila in result.all()]

    async def _active_staff(self, only_staff_id: str | None) -> list[tuple[str, str]]:
        """``(id, display_name)`` del personal activo, por columnas: cargar
        ``Staff`` como entidad disparaba sus dos relaciones (F3-04)."""
        query = select(Staff.id, Staff.display_name).where(
            Staff.is_active.is_(True), *self._store_scope(Staff.store_id)
        )
        if only_staff_id:
            query = query.where(Staff.id == only_staff_id)
        result = await self.db.execute(query.order_by(Staff.display_name.asc()))
        return [(staff_id, name) for staff_id, name in result.all()]

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
        """Bloqueos activos que se superponen con el rango, por profesional.

        El predicado es el compartido (``active_block_overlap``, F1-13): la
        tienda y ``end_time > inicio`` sobre el indice
        ``ix_appointment_blocks_store_staff_end``.
        """
        result = await self.db.execute(
            select(StaffBlock).where(
                StaffBlock.staff_id.in_(staff_ids),
                active_block_overlap(self.store_id, start_dt, end_dt),
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
        staff_ids = [staff_id for staff_id, _ in staff_members]
        if not staff_ids:
            return ProfessionalReportsResponse(
                from_date=resolved_from, to_date=resolved_to, professionals=[]
            )

        schedules_by_staff = await self._schedules_by_staff(staff_ids)
        blocks_by_staff = await self._blocks_by_staff(
            staff_ids, start_dt=start_dt, end_dt=end_dt
        )
        # Conteos, minutos e ingreso por profesional, agregados en la base
        # (regla 11); mismo criterio de ingreso que el resumen.
        totals_by_staff = await self._staff_totals(
            start_dt=start_dt, end_dt=end_dt, staff_id=only_staff_id
        )
        total_days = (resolved_to - resolved_from).days + 1
        items = [
            _professional_item(
                staff_id,
                staff_name,
                totals_by_staff.get(staff_id, _EMPTY_STAFF_TOTALS),
                available_minutes=_available_minutes(
                    schedules_by_staff.get(staff_id, []), resolved_from, total_days
                ),
                blocked_minutes=_blocked_minutes(
                    blocks_by_staff.get(staff_id, []), start_dt, end_dt
                ),
            )
            for staff_id, staff_name in staff_members
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

    async def get_audit_logs(
        self, *, limit: int, offset: int, resource_id: str | None = None
    ) -> list[AuditLogItem]:
        """Auditoria de turnos y bloqueos de la tienda del reporte (B5-12).

        ``audit_logs`` no tiene RLS: sin tienda no hay lectura posible.
        """
        store_id = self.store_id
        if store_id is None:
            raise ValueError("La auditoria siempre se lee acotada a una tienda")
        logs = await AuditRepository(self.db).list_store_resource_logs(
            store_id=store_id,
            resource_types=AUDITED_SCHEDULE_RESOURCES,
            limit=limit,
            offset=offset,
            resource_id=resource_id,
        )
        return [
            AuditLogItem(
                id=str(log.id),
                created_at=log.created_at,
                actor_email=log.actor_email,
                resource_type=log.resource_type,
                resource_id=log.resource_id,
                action=log.action,
                payload_before=log.payload_before,
                payload_after=log.payload_after,
            )
            for log in logs
        ]
