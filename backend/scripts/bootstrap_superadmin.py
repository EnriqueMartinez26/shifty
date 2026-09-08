"""Bootstrap idempotente del primer SuperAdmin.

Variables requeridas:
- SUPERADMIN_EMAIL
- SUPERADMIN_PASSWORD

Variables opcionales:
- SUPERADMIN_FIRST_NAME
- SUPERADMIN_LAST_NAME
- SUPERADMIN_STORE_SLUG
- SUPERADMIN_STORE_NAME
"""

import asyncio
import os
import sys
from pathlib import Path

from pydantic import EmailStr, TypeAdapter, ValidationError
from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.database import AsyncSessionFactory, _apply_tenant_context, set_tenant_context
from core.validation import validate_password_strength
from core.security import hash_password
from modules.stores.model import Store
from modules.users.model import User, UserRole


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Falta la variable de entorno {name}")
    return value


_EMAIL = TypeAdapter(EmailStr)


def validate_superadmin_email(raw: str) -> str:
    """Valida el email con el MISMO criterio que el login (EmailStr).

    Sin esto se podia crear el primer superadmin con un email que el login
    rechaza (p.ej. admin@shifty.local: dominio reservado, 422), dejando la
    plataforma sin ningun superadmin capaz de entrar y sin forma de
    arreglarlo desde la UI. Mejor fallar aca, antes de escribir nada.
    """
    try:
        return str(_EMAIL.validate_python(raw.strip())).lower()
    except ValidationError as exc:
        detail = (
            exc.errors()[0].get("msg", "email invalido")
            if exc.errors()
            else "email invalido"
        )
        raise RuntimeError(
            f"SUPERADMIN_EMAIL invalido ({detail}). Usa un email real con dominio "
            "publico: es el que vas a usar para entrar al panel."
        ) from exc


async def bootstrap() -> None:
    email = validate_superadmin_email(_required_env("SUPERADMIN_EMAIL"))
    password = _required_env("SUPERADMIN_PASSWORD")
    # La cuenta mas privilegiada del sistema pasa por la MISMA politica que el
    # resto (min 12 + denylist), no un piso mas debil.
    try:
        validate_password_strength(password)
    except ValueError as exc:
        raise RuntimeError(f"SUPERADMIN_PASSWORD invalida: {exc}") from exc

    first_name = os.getenv("SUPERADMIN_FIRST_NAME", "Shifty").strip() or "Shifty"
    last_name = os.getenv("SUPERADMIN_LAST_NAME", "SuperAdmin").strip() or "SuperAdmin"
    store_slug = (
        os.getenv("SUPERADMIN_STORE_SLUG", "shifty-internal").strip()
        or "shifty-internal"
    )
    store_name = (
        os.getenv("SUPERADMIN_STORE_NAME", "Shifty Internal").strip()
        or "Shifty Internal"
    )

    set_tenant_context(None, True)
    async with AsyncSessionFactory() as db:
        await _apply_tenant_context(db)

        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()

        if user:
            user.role = UserRole.ADMIN
            user.is_global_admin = True
            user.is_active = True
            user.hashed_password = hash_password(password)
            user.first_name = user.first_name or first_name
            user.last_name = user.last_name or last_name
            user.full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
            await db.commit()
            print(f"SuperAdmin actualizado: {email}")
            return

        store_result = await db.execute(select(Store).where(Store.slug == store_slug))
        store = store_result.scalar_one_or_none()
        if store is None:
            store = Store(name=store_name, slug=store_slug)
            store.public_id = store.id
            db.add(store)
            await db.flush()

        user = User(
            email=email,
            hashed_password=hash_password(password),
            first_name=first_name,
            last_name=last_name,
            full_name=f"{first_name} {last_name}".strip(),
            role=UserRole.ADMIN,
            store_id=store.id,
            is_global_admin=True,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        print(f"SuperAdmin creado: {email}")


if __name__ == "__main__":
    asyncio.run(bootstrap())
