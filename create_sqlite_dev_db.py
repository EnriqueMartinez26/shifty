import sys
import os
import asyncio

# Ensure backend path is in sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

# Load environment
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "backend", ".env"))

from sqlalchemy.ext.asyncio import create_async_engine
from core.models import Base

# Import all models to register in metadata
import modules.stores.model
import modules.users.model
import modules.services.model
import modules.staff.model
import modules.appointments.model
import modules.budget.model
import modules.audit.model

async def main():
    db_url = "sqlite+aiosqlite:///shifty_dev.db"
    print(f"Creating SQLite database at {db_url}...")
    engine = create_async_engine(db_url, echo=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables created successfully!")

if __name__ == "__main__":
    asyncio.run(main())
