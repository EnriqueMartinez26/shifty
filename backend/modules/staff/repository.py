from datetime import time
from typing import Any

from sqlalchemy import delete, exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.interfaces import LoaderOption
from sqlalchemy.sql import Select

from core.security import hash_password
from infrastructure.persistence.models.staff_service import StaffServiceModel
from modules.services.model import Service
from infrastructure.persistence.models.staff import (
    STAFF_KIND_PERSON,
    STAFF_KIND_RESOURCE,
)
from modules.staff.model import Schedule, Staff
from modules.auth.service import revoke_sessions_for_user
from modules.users.model import User, UserRole
import ulid

# La cuenta del profesional nace sin clave usable hasta que se le asigna una.
# Hashear un ULID al azar en cada alta era
# bcrypt sincrono (~250 ms) con el loop congelado (F1-06, R8-03). Se calcula
# UNA vez al importar, igual que el de los clientes del portal
# (public_api/repository.py): sigue siendo un bcrypt valido que no verifica
# contra nada tipeable.
_UNUSABLE_STAFF_PASSWORD_HASH = hash_password(str(ulid.ULID()))


def _active_services(store_id: str) -> LoaderOption:
    """Carga de la relacion con SOLO los servicios activos de ESA tienda.

    El filtro va en el JOIN y no re-asignando la coleccion: re-asignar una
    relacion `secondary` marca las filas sobrantes de `staff_services` para
    DELETE, asi que una lectura borraba la asignacion (y su `rating`) del
    servicio desactivado (AUD2-B6-01 / AUD2-B6-02).

    El predicado `store_id` no es redundante con `Staff.store_id`: es uno de
    los filtros de tienda que CLAUDE.md §2 pide no quitar, defensa en
    profundidad sobre RLS para una fila cruzada de `staff_services`. Se
    construye por llamada porque el `store_id` es del request, igual que en
    `modules/public_api/repository.get_staff`.

    CUIDADO: la garantia depende de que nadie cargue el mismo `Staff` antes en
    el MISMO request. `Staff.services` es `lazy="selectin"`, asi que un
    `select(Staff)` sin esta opcion trae la coleccion COMPLETA, y la sesion no
    refresca una coleccion ya cargada salvo con `populate_existing()`: el
    objeto del identity map se quedaria con los servicios inactivos adentro y
    la proxima escritura volveria a marcarlos para DELETE.
    """
    return selectinload(
        Staff.services.and_(
            Service.is_active == True,
            Service.store_id == store_id,
        )
    )


def _visible_para_el_panel(
    query: Select[tuple[Staff]], include_global_admins: bool
) -> Select[tuple[Staff]]:
    """Esconde al profesional cuya cuenta de login es superadmin.

    Misma regla que ``UserRepository`` (S-15): para un admin de tienda la
    cuenta global no existe, y eso vale tambien para las lecturas de
    ``/staff/`` (AUD2-B3-11). Sin esto el panel listaba con su email a un
    profesional ascendido a superadmin mientras ``GET /users/`` lo ocultaba
    y ``PUT /staff/{id}`` sobre el daba 404. Un recurso (cancha, sala) no
    tiene usuario y nunca cae en el filtro.
    """
    if include_global_admins:
        return query
    es_global = exists().where(User.id == Staff.id, User.is_global_admin.is_(True))
    return query.where(~es_global)


class StaffRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _get_services_for_store(
        self, service_public_ids: list[str], store_id: str
    ) -> list[Service]:
        if not service_public_ids:
            return []

        result = await self.db.execute(
            select(Service).where(
                Service.public_id.in_(service_public_ids),
                Service.store_id == store_id,
                Service.is_active == True,
            )
        )
        services = list(result.scalars().all())
        if len(services) != len(set(service_public_ids)):
            raise ValueError(
                "Uno o más servicios no existen o no pertenecen al negocio"
            )
        return services

    async def create(
        self, data: dict[str, Any], store_id: str, service_public_ids: list[str]
    ) -> Staff:
        """Alta sin commit (lo hace StaffService)."""
        services = await self._get_services_for_store(service_public_ids, store_id)
        kind = str(data.get("kind") or STAFF_KIND_PERSON)
        if kind == STAFF_KIND_RESOURCE:
            # Un recurso (cancha, sala) no tiene usuario ni email: solo es un
            # calendario reservable.
            resource = Staff(
                id=str(ulid.ULID()),
                kind=STAFF_KIND_RESOURCE,
                first_name=data.get("first_name") or "",
                last_name=data.get("last_name") or "",
                email=None,
                display_name=data["display_name"],
                store_id=store_id,
                service_ids=[service.public_id for service in services],
            )
            resource.services = services
            self.db.add(resource)
            await self.db.flush()
            return resource

        # Normalizamos el email igual que el login (lower). La unicidad
        # case-insensitive la garantiza el indice uq_users_email_lower: este
        # pre-chequeo es el mensaje amable (regla 16), con limit(1) para no dar
        # 500 ante duplicados heredados. En la carrera SELECT/INSERT decide el
        # indice: la IntegrityError sube hasta main.py y sale como 409.
        email = str(data["email"]).strip().lower()
        user_res = await self.db.execute(
            select(User.id).where(func.lower(User.email) == email).limit(1)
        )
        if user_res.first() is not None:
            raise ValueError("Ya existe un usuario con ese email")

        user = User(
            email=email,
            hashed_password=_UNUSABLE_STAFF_PASSWORD_HASH,
            first_name=data["first_name"],
            last_name=data["last_name"],
            role=UserRole.STAFF,
            store_id=store_id,
        )
        self.db.add(user)
        await self.db.flush()

        new_staff = Staff(
            id=user.id,
            kind=STAFF_KIND_PERSON,
            first_name=data["first_name"],
            last_name=data["last_name"],
            email=email,
            display_name=data["display_name"],
            store_id=store_id,
            service_ids=[service.public_id for service in services],
        )
        new_staff.services = services
        self.db.add(new_staff)
        await self.db.flush()
        return new_staff

    async def get_all(
        self, store_id: str, *, include_global_admins: bool = False
    ) -> list[Staff]:
        query = (
            select(Staff)
            .where(
                Staff.store_id == store_id,
                Staff.is_active == True,
            )
            .options(
                selectinload(Staff.schedules),
                _active_services(store_id),
            )
        )
        result = await self.db.execute(
            _visible_para_el_panel(query, include_global_admins)
        )
        # La carga ya trae solo los activos de la tienda: no se filtra ni se
        # re-asigna nada (ver `_active_services`).
        return list(result.scalars().all())

    async def get_by_id(
        self, public_id: str, store_id: str, *, include_global_admins: bool = False
    ) -> Staff | None:
        query = (
            select(Staff)
            .where(
                Staff.id == public_id,
                Staff.store_id == store_id,
            )
            .options(
                selectinload(Staff.schedules),
                _active_services(store_id),
            )
        )
        result = await self.db.execute(
            _visible_para_el_panel(query, include_global_admins)
        )
        # Antes esto re-consultaba con `_get_services_for_store`, que exige que
        # TODOS los ids existan y esten activos: un servicio borrado dejaba en
        # 500 la ficha del profesional y todo lo que la usa (AUD2-B6-01).
        return result.scalar_one_or_none()

    async def _assert_no_overlap(
        self,
        staff: Staff,
        *,
        day_of_week: int,
        start: time,
        end: time,
        exclude_id: str | None = None,
    ) -> None:
        """Impide franjas superpuestas o duplicadas para el mismo dia.

        Antes se podia cargar dos veces el mismo rango y el booking publico
        mostraba cada horario repetido: el cliente veia "09:00" dos veces.
        Dos franjas separadas el mismo dia (manana y tarde) siguen siendo
        validas mientras no se toquen.
        """
        filtros = [Schedule.staff_id == staff.id, Schedule.day_of_week == day_of_week]
        if exclude_id:
            filtros.append(Schedule.id != exclude_id)
        existentes = (await self.db.execute(select(Schedule).where(*filtros))).scalars()

        for otro in existentes:
            if start < otro.end_time and end > otro.start_time:
                raise ValueError(
                    "El horario se superpone con otra franja de ese dia "
                    f"({otro.start_time.strftime('%H:%M')}-"
                    f"{otro.end_time.strftime('%H:%M')})"
                )

    async def add_schedule(
        self, staff: Staff, schedule_data: dict[str, Any], store_id: str
    ) -> Schedule:
        await self._assert_no_overlap(
            staff,
            day_of_week=schedule_data["day_of_week"],
            start=schedule_data["start_time"],
            end=schedule_data["end_time"],
        )
        new_schedule = Schedule(**schedule_data, staff_id=staff.id, store_id=store_id)
        self.db.add(new_schedule)
        await self.db.flush()
        return new_schedule

    async def get_schedule(self, staff: Staff, schedule_id: str) -> Schedule | None:
        result = await self.db.execute(
            select(Schedule).where(
                Schedule.id == schedule_id, Schedule.staff_id == staff.id
            )
        )
        return result.scalar_one_or_none()

    async def update_schedule(
        self, staff: Staff, schedule: Schedule, cambios: dict[str, Any]
    ) -> Schedule:
        day = cambios.get("day_of_week", schedule.day_of_week)
        start = cambios.get("start_time", schedule.start_time)
        end = cambios.get("end_time", schedule.end_time)
        if start >= end:
            raise ValueError("La hora de inicio debe ser anterior a la de fin")

        await self._assert_no_overlap(
            staff, day_of_week=day, start=start, end=end, exclude_id=schedule.id
        )

        schedule.day_of_week = day
        schedule.start_time = start
        schedule.end_time = end
        await self.db.flush()
        return schedule

    async def delete_schedule(self, schedule: Schedule) -> None:
        await self.db.delete(schedule)
        await self.db.flush()

    async def _set_services(self, staff: Staff, services_list: list[Service]) -> None:
        """Deja al profesional con EXACTAMENTE los servicios de la lista.

        La coleccion cargada solo trae los activos de la tienda, asi que
        SQLAlchemy por si solo no puede borrar la asignacion a un servicio
        desactivado: el PATCH respondia 200 y la fila sobrevivia, y al
        reactivar el servicio volvia a la ficha sin que nadie lo pidiera.
        Se borra dirigido lo que no esta en la lista nueva.

        Esto NO reabre AUD2-B6-02: ahi el problema era que una LECTURA del
        portal borraba. Aca el borrado es la lista explicita del dueno.
        """
        staff.service_ids = [service.public_id for service in services_list]
        staff.services = services_list
        await self.db.flush()

        sobrantes = delete(StaffServiceModel).where(
            StaffServiceModel.staff_id == staff.id
        )
        conservar = [service.id for service in services_list]
        if conservar:
            sobrantes = sobrantes.where(StaffServiceModel.service_id.not_in(conservar))
        await self.db.execute(sobrantes)

    async def update_services(
        self, staff: Staff, service_public_ids: list[str]
    ) -> Staff:
        services_list = await self._get_services_for_store(
            service_public_ids,
            staff.store_id,
        )
        await self._set_services(staff, services_list)
        return staff

    async def update_profile(
        self,
        staff: Staff,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        email: str | None = None,
        display_name: str | None = None,
        service_public_ids: list[str] | None = None,
        is_active: bool | None = None,
    ) -> Staff:
        if email is not None:
            email = email.strip().lower()
        if email is not None and email != staff.email:
            # Mensaje amable; la garantia es uq_users_email_lower (ver create).
            existing_res = await self.db.execute(
                select(User.id)
                .where(func.lower(User.email) == email, User.id != staff.id)
                .limit(1)
            )
            if existing_res.first() is not None:
                raise ValueError("Ya existe un usuario con ese email")

        if first_name is not None:
            staff.first_name = first_name
        if last_name is not None:
            staff.last_name = last_name
        if email is not None:
            staff.email = email
        if display_name is not None:
            staff.display_name = display_name
        if is_active is not None:
            staff.is_active = is_active
        if service_public_ids is not None:
            # `PATCH /staff/{id}` con `service_ids` es la misma lista explicita
            # que `PATCH /staff/{id}/services`: mismo borrado dirigido.
            services_list = await self._get_services_for_store(
                service_public_ids,
                staff.store_id,
            )
            await self._set_services(staff, services_list)

        # Solo una persona tiene usuario que sincronizar; un recurso no.
        user = None
        if getattr(staff, "kind", STAFF_KIND_PERSON) == STAFF_KIND_PERSON:
            user_res = await self.db.execute(select(User).where(User.id == staff.id))
            user = user_res.scalar_one_or_none()
        if user:
            user.first_name = staff.first_name
            user.last_name = staff.last_name
            if staff.email:
                user.email = staff.email
            user.full_name = f"{staff.first_name or ''} {staff.last_name or ''}".strip()
            if is_active is not None:
                user.is_active = is_active
                # Desactivar al profesional corta sus sesiones vivas, igual que
                # en users/superadmin: sin esto, al reactivarlo sus refresh
                # tokens de 30 dias volverian a funcionar.
                if not is_active:
                    await revoke_sessions_for_user(self.db, user.id)

        await self.db.flush()
        return staff

    async def get_linked_user(self, staff: Staff) -> User | None:
        """Cuenta de login del profesional (Staff.id == User.id). Un recurso no tiene."""
        if getattr(staff, "kind", STAFF_KIND_PERSON) != STAFF_KIND_PERSON:
            return None
        result = await self.db.execute(select(User).where(User.id == staff.id))
        return result.scalar_one_or_none()

    async def soft_delete(self, staff: Staff) -> None:
        """Baja sin commit (lo hace StaffService)."""
        staff.is_active = False
        # Por id, no por email: un recurso no tiene email y una persona podia
        # tener el email cambiado en users sin pasar por aca.
        user_res = await self.db.execute(select(User).where(User.id == staff.id))
        user = user_res.scalar_one_or_none()
        if user:
            user.is_active = False
            await revoke_sessions_for_user(self.db, user.id)
        await self.db.flush()
