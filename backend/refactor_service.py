import re

file_path = "modules/appointments/service.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Imports
content = content.replace("from sqlalchemy.ext.asyncio import AsyncSession", "from core.uow import AbstractUnitOfWork\nimport ulid")
content = content.replace("\nfrom sqlalchemy import select\n", "\n") 
content = content.replace("from modules.appointments.repository import AppointmentRepository\n", "")
content = content.replace("from modules.audit.service import AuditService\n", "")

# Constructor
constructor_old = '''    def __init__(self, db: AsyncSession, redis: Redis) -> None:
        self.db = db
        self.redis = redis
        self._repo = AppointmentRepository(db)
        self._audit = AuditService(db)'''
constructor_new = '''    def __init__(self, uow: AbstractUnitOfWork, redis: Redis) -> None:
        self.uow = uow
        self.redis = redis'''
content = content.replace(constructor_old, constructor_new)

# Replacements for `self._repo` and `self._audit`
content = content.replace("self._repo", "self.uow.appointments")
content = content.replace("self._audit", "self.uow.audit")

# book method
book_old_add = '''        appointment = Appointment(
            store_id=store_id,
            staff_id=staff.id,
            service_id=service.id,
            client_id=actor.id,
            starts_at=starts_at,
            notes=data.get("notes"),
            idempotency_key=data.get("idempotency_key"),
        )
        self.db.add(appointment)
        await self.db.flush()  # obtener id sin cerrar la transacción'''
book_new_add = '''        appointment = Appointment(
            public_id=str(ulid.ULID()),
            store_id=store_id,
            staff_id=staff.id,
            service_id=service.id,
            client_id=actor.id,
            starts_at=starts_at,
            notes=data.get("notes"),
            idempotency_key=data.get("idempotency_key"),
        )
        self.uow.appointments.add(appointment)'''
content = content.replace(book_old_add, book_new_add)

# reschedule queries
reschedule_svc_old = '''        from sqlalchemy import select
        svc_res = await self.db.execute(
            select(Service).where(Service.id == service_id)
        )
        service = svc_res.scalar_one_or_none()'''
reschedule_svc_new = '''        service = await self.uow.appointments.get_service_by_id(service_id)'''
content = content.replace(reschedule_svc_old, reschedule_svc_new)

reschedule_staff_old = '''        staff_res = await self.db.execute(
            select(Staff).where(Staff.id == staff_id)
        )
        staff = staff_res.scalar_one_or_none()'''
reschedule_staff_new = '''        staff = await self.uow.appointments.get_staff_by_id(staff_id)'''
content = content.replace(reschedule_staff_old, reschedule_staff_new)

# reschedule add
reschedule_add_old = '''        new_appointment = Appointment(
            store_id=store_id,
            staff_id=staff_id,
            service_id=service_id,
            client_id=client_id,
            starts_at=new_starts_at,
            notes=orig_notes,
            idempotency_key=idempotency_key,
        )
        self.db.add(new_appointment)
        await self.db.flush()'''
reschedule_add_new = '''        new_appointment = Appointment(
            public_id=str(ulid.ULID()),
            store_id=store_id,
            staff_id=staff_id,
            service_id=service_id,
            client_id=client_id,
            starts_at=new_starts_at,
            notes=orig_notes,
            idempotency_key=idempotency_key,
        )
        self.uow.appointments.add(new_appointment)'''
content = content.replace(reschedule_add_old, reschedule_add_new)

# replace db.commit() and db.refresh()
content = content.replace("        await self.db.commit()\n        await self.db.refresh(appointment)\n", "        await self.uow.commit()\n")
content = content.replace("        await self.db.commit()\n        await self.db.refresh(new_appointment)\n", "        await self.uow.commit()\n")

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
print("Refactored service.py")
