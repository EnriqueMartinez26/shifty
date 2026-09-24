"""
Repositorio publico del turnero.

Responsabilidades:
- Resolucion de stores, servicios y staff para el portal de reservas.
- Identificacion del cliente por telefono.
- Consulta y autogestion publica de turnos.
"""

from decimal import Decimal
from enum import Enum
from core.utils import ARGENTINA_TZ, ensure_utc_aware, local_to_utc
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import ulid

from core.security import hash_password
from modules.appointments.model import Appointment, AppointmentStatus
from modules.auth.service import normalize_email
from modules.appointments.repository import AppointmentRepository
from modules.payments.deposit_rules import ClientHistory
from modules.services.model import Service
from modules.staff.model import Schedule, Staff, StaffBlock
from modules.stores.model import Store
from modules.users.model import User, UserRole

# Los clientes creados en el booking publico NO inician sesion (login/reset les
# esta negado), asi que su hash de password nunca se verifica. Se computa UNA
# sola vez al importar y se reusa, en vez de correr bcrypt (sincrono, 12 rounds,
# ~250ms) en el event loop por cada alta anonima: era un vector de DoS. Sigue
# siendo un hash bcrypt valido, asi que un verify eventual devuelve False sin
# romper (no un formato invalido que lance excepcion).
_UNUSABLE_CLIENT_PASSWORD_HASH = hash_password(str(ulid.ULID()))


def _schedule_covers(
    local_day: date, schedule: Schedule, starts_at: datetime, ends_at: datetime
) -> bool:
    """La jornada de ese dia local, contiene el rango COMPLETO? (AUD2-B1-03)

    Se comparan INSTANTES, no la hora del dia suelta. Con ``time`` un turno
    que termina despues de la medianoche local "daba la vuelta" (23:30 + 60
    min queda en 00:30) y la condicion ``cierre >= fin`` se cumplia sola: un
    POST directo agendaba a las 23:30 contra una jornada de 09:00 a 18:00.
    De paso queda cubierto el caso de que el fin caiga en otro dia local.
    """
    apertura = local_to_utc(local_day, schedule.start_time)
    cierre = local_to_utc(local_day, schedule.end_time)
    return apertura <= starts_at and ends_at <= cierre


class RangeRejection(str, Enum):
    """Por que un profesional no puede tomar un rango (``staff_can_take_range``)."""

    OUT_OF_SCHEDULE = "out_of_schedule"
    BLOCKED = "blocked"
    TAKEN = "taken"


class PublicRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_store_by_slug(self, slug: str) -> Store | None:
        result = await self.db.execute(
            select(Store).where(Store.slug == slug, Store.is_active == True)
        )
        return result.scalar_one_or_none()

    async def get_store_by_public_id(self, public_id: str) -> Store | None:
        result = await self.db.execute(
            select(Store).where(Store.public_id == public_id, Store.is_active == True)
        )
        return result.scalar_one_or_none()

    async def get_store_by_id(self, store_id: str) -> Store | None:
        result = await self.db.execute(
            select(Store).where(Store.id == store_id, Store.is_active == True)
        )
        return result.scalar_one_or_none()

    async def get_services(self, store_id: str) -> list[Service]:
        result = await self.db.execute(
            select(Service).where(
                Service.store_id == store_id, Service.is_active == True
            )
        )
        return list(result.scalars().all())

    async def get_service_by_public_id(self, public_id: str) -> Service | None:
        result = await self.db.execute(
            select(Service)
            .join(Store, Service.store_id == Store.id)
            .where(
                Service.public_id == public_id,
                Service.is_active == True,
                Store.is_active == True,
            )
        )
        return result.scalar_one_or_none()

    async def get_staff(
        self, store_id: str, service_public_id: str | None = None
    ) -> list[Staff]:
        # El filtro de activos va en el JOIN de la carga, no re-asignando
        # `member.services`: asignar sobre una relacion `secondary` marca las
        # filas sobrantes de `staff_services` para DELETE, asi que una lectura
        # del portal borraba de verdad la asignacion del servicio desactivado
        # (y su `rating`) en el commit siguiente (AUD2-B6-02, 2026-09-20).
        # Sigue siendo una sola query extra, como el batch que reemplaza, y
        # conserva el filtro por `store_id` como defensa en profundidad.
        #
        # CUIDADO: la garantia depende de que nadie cargue el mismo `Staff`
        # antes en el MISMO request. `Staff.services` es `lazy="selectin"`, asi
        # que un `select(Staff)` sin esta opcion trae la coleccion COMPLETA, y
        # la sesion no refresca una coleccion ya cargada salvo con
        # `populate_existing()`: el objeto del identity map se quedaria con los
        # servicios inactivos adentro y la proxima escritura de la request
        # volveria a marcarlos para DELETE.
        result = await self.db.execute(
            select(Staff)
            .options(
                selectinload(
                    Staff.services.and_(
                        Service.is_active == True,
                        Service.store_id == store_id,
                    )
                )
            )
            .where(Staff.store_id == store_id, Staff.is_active == True)
        )
        staff_members = list(result.scalars().all())
        if service_public_id:
            staff_members = [
                member
                for member in staff_members
                if service_public_id in (member.service_ids or [])
            ]
        return staff_members

    async def get_or_create_client(
        self,
        store_id: str,
        phone: str,
        name: str,
        email: str | None,
    ) -> User:
        """Busca o crea el cliente de la tienda por telefono.

        El flujo publico NUNCA pisa el email ni el nombre de una ficha que ya
        existe. El telefono no prueba identidad: sin esa guarda, cualquiera que
        conociera un telefono se anotaba en la lista de espera con su propio
        email y desde ahi recibia los mails del cliente real (confirmaciones,
        recordatorios y sus datos de turno). 2026-09-10.

        Hasta el 2026-09-20 existia una excepcion (``adopt_contact``) para el
        telefono "verificado por OTP". Sintoma: el OTP prueba posesion del
        EMAIL y ``/public/otp/request`` es publico, asi que quien pedia el
        codigo elegia el buzon; pedirlo al email propio con el telefono de otro
        adoptaba su ficha. La excepcion se fue del todo: el mail de ESTA reserva
        sigue yendo al email que dejaron, pero no queda pegado al cliente.

        El email se normaliza a minusculas antes de buscar y antes de escribir
        (regla 16). Este es el camino que mas filas ``users`` crea y era el
        unico que lo guardaba crudo: la busqueda exacta no encontraba la fila
        escrita con otra capitalizacion y el INSERT chocaba contra el indice
        funcional ``uq_users_email_lower`` (AUD2-B3-04, 2026-09-20).
        """
        email = normalize_email(email) if email else None
        # Dos clientes con el mismo telefono (alta vieja sin unicidad) rompian
        # con MultipleResultsFound -> 500. Se toma el mas reciente.
        result = await self.db.execute(
            select(User)
            .where(
                User.phone == phone,
                User.store_id == store_id,
                User.role == UserRole.CLIENT,
            )
            .order_by(User.created_at.desc())
            .limit(1)
        )
        existing = result.scalars().first()

        if existing:
            return existing

        # El tecnico tambien va en minusculas: el store_id es un ULID en
        # mayusculas y la base exige el email normalizado
        # (ck_users_email_lower, F1-12).
        technical_email = email or f"{phone}@store{store_id}.noreply".lower()
        new_client = User(
            email=technical_email,
            hashed_password=_UNUSABLE_CLIENT_PASSWORD_HASH,
            full_name=name,
            phone=phone,
            role=UserRole.CLIENT,
            store_id=store_id,
        )
        self.db.add(new_client)
        await self.db.flush()
        return new_client

    async def staff_can_take_range(
        self,
        staff_id: str,
        starts_at: datetime,
        ends_at: datetime,
        *,
        buffer_minutes: int,
        exclude_appointment_id: str | None = None,
    ) -> RangeRejection | None:
        """Este profesional, puede tomar este rango? ``None`` si puede.

        Unica respuesta para el alta y para la reprogramacion del cliente
        (B1-19): antes el router tenia su propia copia (dos metodos privados
        de aca, un lock y una consulta de choque a mano) y las dos divergieron
        (B1-05 orden del lock, B1-07 buffer). Si devuelve ``None`` el
        profesional queda lockeado hasta el commit.
        """
        if staff_id not in await self._staff_ids_with_schedule_for_slot(
            [staff_id], starts_at, ends_at
        ):
            return RangeRejection.OUT_OF_SCHEDULE
        return await self._lock_and_recheck(
            staff_id,
            starts_at,
            ends_at,
            buffer_minutes=buffer_minutes,
            exclude_appointment_id=exclude_appointment_id,
        )

    async def _lock_and_recheck(
        self,
        staff_id: str,
        starts_at: datetime,
        ends_at: datetime,
        *,
        buffer_minutes: int,
        exclude_appointment_id: str | None = None,
    ) -> RangeRejection | None:
        """Lock del profesional y, BAJO el lock, bloqueo y choque (regla 4).

        El lock va antes de la lectura que decide: leer el bloqueo sin el lock
        dejaba colar una reserva dentro de un bloqueo recien creado (carrera
        reproducida en tests/postgres/test_pg_bloqueos.py). El lock y las dos
        lecturas son las del panel (``AppointmentRepository.lock_and_read_range``,
        S-07); aca solo se traducen a ``RangeRejection``.
        """
        block, conflict = await AppointmentRepository(self.db).lock_and_read_range(
            staff_id,
            starts_at,
            ends_at,
            buffer_minutes=max(0, buffer_minutes),
            exclude_appointment_id=exclude_appointment_id,
        )
        # Mismo orden de prioridad que el panel: el bloqueo gana al choque.
        if block is not None:
            return RangeRejection.BLOCKED
        if conflict is not None:
            return RangeRejection.TAKEN
        return None

    async def _staff_ids_with_schedule_for_slot(
        self, staff_ids: list[str], starts_at: datetime, ends_at: datetime
    ) -> set[str]:
        """Profesionales (de ``staff_ids``) cuya agenda cubre el rango. Una consulta.

        El horario del profesional esta cargado en hora ARGENTINA (09:00 a
        18:00); el turno llega como instante UTC. Comparar en UTC rechazaba
        las ultimas 3 horas de cada jornada y todo turno posterior a las
        21:00 (cae en el dia UTC siguiente). 2026-09-10.
        """
        if not staff_ids:
            return set()
        starts_utc = ensure_utc_aware(starts_at)
        ends_utc = ensure_utc_aware(ends_at)
        local_start = starts_utc.astimezone(ARGENTINA_TZ)
        schedules_result = await self.db.execute(
            select(Schedule).where(
                Schedule.staff_id.in_(staff_ids),
                Schedule.day_of_week == local_start.weekday(),
            )
        )
        return {
            schedule.staff_id
            for schedule in schedules_result.scalars().all()
            if _schedule_covers(local_start.date(), schedule, starts_utc, ends_utc)
        }

    async def _staff_ids_with_overlapping_block(
        self, staff_ids: list[str], starts_at: datetime, ends_at: datetime
    ) -> set[str]:
        """Profesionales (de ``staff_ids``) con un bloqueo activo que solapa. Una consulta.

        Lectura en lote SIN lock que solo descarta candidatos (B1-13); la
        decision bajo lock es ``lock_and_read_range`` (S-07).

        Pregunta de existencia, no de unicidad: dos bloqueos solapados del
        mismo profesional (el alta lo permite) hacian que scalar_one_or_none
        levantara MultipleResultsFound y la reserva saliera 500 (B1-02).
        """
        if not staff_ids:
            return set()
        blocks_result = await self.db.execute(
            select(StaffBlock.staff_id)
            .where(
                StaffBlock.staff_id.in_(staff_ids),
                StaffBlock.is_active.is_(True),
                StaffBlock.starts_at < ends_at,
                StaffBlock.ends_at > starts_at,
            )
            .distinct()
        )
        return set(blocks_result.scalars().all())

    async def _staff_ids_with_conflicting_appointment(
        self,
        staff_ids: list[str],
        starts_at: datetime,
        ends_at: datetime,
        buffer_minutes: int,
    ) -> set[str]:
        """Profesionales (de ``staff_ids``) con un turno activo que choca. Una consulta.

        Solo la lectura en lote SIN lock que DESCARTA candidatos del alta
        (B1-13); la decision bajo lock es ``lock_and_read_range`` (S-07). Mismo
        criterio: estados activos y el turno vecino ensanchado por el buffer.
        """
        if not staff_ids:
            return set()
        buffer = timedelta(minutes=max(0, buffer_minutes))
        conflict_res = await self.db.execute(
            select(Appointment.staff_id)
            .where(
                Appointment.staff_id.in_(staff_ids),
                Appointment.status.in_(
                    [
                        AppointmentStatus.PENDING.value,
                        AppointmentStatus.PENDING_PAYMENT.value,
                        AppointmentStatus.CONFIRMED.value,
                    ]
                ),
                Appointment.starts_at < ends_at + buffer,
                Appointment.ends_at > starts_at - buffer,
            )
            .distinct()
        )
        return set(conflict_res.scalars().all())

    async def _pick_staff_for_slot(
        self,
        candidates: list[Staff],
        starts_at: datetime,
        ends_at: datetime,
        buffer_minutes: int,
    ) -> Staff | None:
        """Primer candidato (en el orden dado) que puede tomar el rango, ya lockeado.

        Horarios, bloqueos y choques de TODOS los candidatos se leen en lote
        (regla 12, B1-13): antes eran hasta 4 consultas y un ``FOR UPDATE``
        por candidato, y los locks de los descartados quedaban tomados hasta
        el commit. La lectura en lote solo DESCARTA: el elegido se lockea y
        bajo el lock se releen bloqueo y choque (regla 4), porque entre la
        lectura y el lock otra transaccion pudo ocuparlo. El bucle solo da
        mas de una vuelta cuando eso pasa.

        Orden de los locks (S-11): aca se lockea de a uno y en el orden de
        desempate (display_name, public_id), no por id como el alta de
        bloqueos (``lock_staff_rows``). En el camino normal se toma UN solo
        lock y no puede haber ciclo. Un segundo lock solo aparece si el
        elegido fallo la relectura bajo lock; en ese caso, y solo si a la vez
        un cierre de tienda tiene tomado al segundo y espera al primero,
        Postgres detecta el deadlock y aborta una de las dos transacciones.
        No se unifica el orden porque lockear por id cambiaria a quien se le
        asigna el turno o volveria a lockear a todos los candidatos (B1-13).
        """
        ids = [member.id for member in candidates]
        with_schedule = await self._staff_ids_with_schedule_for_slot(
            ids, starts_at, ends_at
        )
        ids = [staff_id for staff_id in ids if staff_id in with_schedule]
        # Con un solo candidato (profesional elegido por el cliente) el
        # descarte previo no ahorra nada: decide directo la relectura.
        taken: set[str] = set()
        if len(ids) > 1:
            taken = await self._staff_ids_with_overlapping_block(
                ids, starts_at, ends_at
            )
            taken |= await self._staff_ids_with_conflicting_appointment(
                ids, starts_at, ends_at, buffer_minutes
            )
        for staff in candidates:
            if staff.id not in with_schedule or staff.id in taken:
                continue
            # El horario ya se leyo en lote: decide la relectura bajo lock,
            # la misma que usa staff_can_take_range (B1-19).
            if await self._lock_and_recheck(
                staff.id, starts_at, ends_at, buffer_minutes=buffer_minutes
            ):
                continue
            return staff
        return None

    async def _candidates(
        self, store_id: str, service_public_id: str, staff_public_id: str | None
    ) -> list[Staff]:
        """Profesionales que pueden tomar el turno, en el orden de desempate.

        Con profesional elegido, solo ese (si hace el servicio); con "cualquier
        profesional", todos los que lo hacen por display_name y public_id.
        """
        qualified_staff = await self.get_staff(
            store_id, service_public_id=service_public_id
        )
        if staff_public_id:
            candidates = [
                member
                for member in qualified_staff
                if member.public_id == staff_public_id
            ]
            if not candidates:
                raise ValueError("El profesional no realiza el servicio seleccionado")
        else:
            candidates = sorted(
                qualified_staff,
                key=lambda member: (member.display_name or "", member.public_id),
            )
        if not candidates:
            raise ValueError("No hay profesionales disponibles para este servicio")
        return candidates

    async def create_appointment(
        self,
        store_id: str,
        service_public_id: str,
        staff_public_id: str | None,
        starts_at: datetime,
        client: User,
        notes: str | None,
        intake_answers: dict[str, str] | None,
        idempotency_key: str,
        initial_status: str = AppointmentStatus.PENDING.value,
        buffer_minutes: int = 0,
        price_amount: Decimal | None = None,
        client_email: str | None = None,
    ) -> tuple[Appointment, Service, Staff]:
        svc_res = await self.db.execute(
            select(Service).where(
                Service.public_id == service_public_id,
                Service.store_id == store_id,
                Service.is_active == True,
            )
        )
        service = svc_res.scalar_one_or_none()
        if not service:
            raise ValueError("Servicio no encontrado")

        ends_at = starts_at + timedelta(minutes=service.duration_minutes)
        candidates = await self._candidates(
            store_id, service_public_id, staff_public_id
        )
        selected_staff = await self._pick_staff_for_slot(
            candidates, starts_at, ends_at, buffer_minutes
        )

        if not selected_staff:
            if staff_public_id:
                raise ValueError("El horario ya esta ocupado. Por favor elegi otro.")
            raise ValueError("No hay profesionales disponibles para ese horario")

        new_appointment = Appointment(
            store_id=store_id,
            staff_id=selected_staff.id,
            service_id=service.id,
            client_id=client.id,
            starts_at=starts_at,
            ends_at=ends_at,
            duration_minutes=service.duration_minutes,
            client_name=client.full_name or client.email,
            # Snapshot del contacto de ESTA reserva: el mail de esta reserva
            # va al email que dejaron ahora, sin pisar el del cliente.
            client_email=client_email or client.email,
            client_phone=client.phone,
            notes=notes,
            intake_answers=intake_answers or {},
            idempotency_key=idempotency_key,
            status=initial_status,
            # Precio congelado al reservar (el panel ya lo hacia): un cobro
            # manual posterior no debe usar el precio de lista de hoy.
            price_amount=(
                price_amount
                if price_amount is not None
                else Decimal(str(service.price or 0))
            ),
        )
        self.db.add(new_appointment)
        await self.db.flush()
        await self.db.refresh(new_appointment)

        return new_appointment, service, selected_staff

    async def get_client_history(self, store_id: str, phone: str) -> ClientHistory:
        """Resumen del cliente en la tienda en UNA consulta agregada, antes del
        lock. Cliente nuevo: historial vacio sin crear el usuario todavia."""
        rows = await self.db.execute(
            select(Appointment.status, func.count())
            .join(User, Appointment.client_id == User.id)
            .where(
                Appointment.store_id == store_id,
                User.store_id == store_id,
                User.phone == phone,
                User.role == UserRole.CLIENT,
                Appointment.status.in_(
                    [
                        AppointmentStatus.COMPLETED.value,
                        AppointmentStatus.ABSENT.value,
                        AppointmentStatus.CANCELLED.value,
                    ]
                ),
            )
            .group_by(Appointment.status)
        )
        conteo = {str(estado): int(total) for estado, total in rows.all()}
        return ClientHistory(
            completed=conteo.get(AppointmentStatus.COMPLETED.value, 0),
            absent=conteo.get(AppointmentStatus.ABSENT.value, 0),
            cancelled=conteo.get(AppointmentStatus.CANCELLED.value, 0),
        )

    async def get_client_by_phone(self, store_id: str, phone: str) -> User | None:
        result = await self.db.execute(
            select(User)
            .where(
                User.phone == phone,
                User.store_id == store_id,
                User.role == UserRole.CLIENT,
            )
            .order_by(User.created_at.desc())
            .limit(1)
        )
        return result.scalars().first()

    async def get_client_appointments(
        self, client_id: str, store_id: str
    ) -> list[Appointment]:
        result = await self.db.execute(
            select(Appointment)
            .where(Appointment.client_id == client_id, Appointment.store_id == store_id)
            .options(selectinload(Appointment.service), selectinload(Appointment.staff))
            .order_by(Appointment.starts_at.desc())
        )
        return list(result.scalars().all())
