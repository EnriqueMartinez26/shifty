import asyncio
from core.database import SessionLocal
from modules.stores.model import Store
from sqlalchemy import select


async def check():
    async with SessionLocal() as session:
        result = await session.execute(select(Store))
        stores = result.scalars().all()
        print(f"Encontrados {len(stores)} salones:")
        for s in stores:
            print(f"- {s.name} (slug: {s.slug}, active: {s.is_active})")


if __name__ == "__main__":
    asyncio.run(check())
