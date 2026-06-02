import asyncio
import sys
import os
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

# Add current directory and backend directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from core.config import settings
from core.security import hash_password
from infrastructure.persistence.models.user import UserModel
from infrastructure.persistence.models.store import StoreModel

async def reset_db():
    print(f"Connecting to {settings.DATABASE_URL}...")
    engine = create_async_engine(settings.DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with engine.begin() as conn:
        print("Limpiando base de datos al 100%...")
        await conn.execute(text("""
            TRUNCATE TABLE 
                appointments, 
                appointment_blocks, 
                staff_services, 
                schedules, 
                staff, 
                services, 
                users, 
                stores, 
                audit_logs, 
                budgets, 
                store_schedules 
            RESTART IDENTITY CASCADE;
        """))
        print("Base de datos limpia.")

    async with async_session() as session:
        print("Generando simulación de datos...")
        
        # 1. Crear Store inicial
        store_id = "01J7K9M2N4P6Q8R0S2T4V6W8S1"
        store = StoreModel(
            id=store_id,
            name="Shifty Main Store",
            slug="main",
            is_active=True
        )
        session.add(store)
        
        # 2. Crear Usuario Admin vinculado a la store
        user = UserModel(
            id="01J7K9M2N4P6Q8R0S2T4V6W8X0",
            email="emartinez.03@hotmail.com",
            full_name="Enzo Martinez",
            hashed_password=hash_password("kukimZ10"),
            role="admin",
            is_active=True,
            store_id=store_id
        )
        session.add(user)
        
        await session.commit()
        print(f"Store '{store.name}' creada.")
        print(f"Usuario {user.email} creado con éxito. Contraseña: kukimZ10")

    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(reset_db())
