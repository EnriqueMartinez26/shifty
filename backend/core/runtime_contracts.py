from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine

from core.models import Base


async def ensure_runtime_contracts(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        dialect_name = conn.dialect.name

        def sync_check(sync_conn) -> dict[str, set[str]]:
            inspector = inspect(sync_conn)
            tables = inspector.get_table_names()
            return {
                table_name: {
                    column["name"] for column in inspector.get_columns(table_name)
                }
                for table_name in tables
            }

        columns_by_table = await conn.run_sync(sync_check)

        if (
            "stores" in columns_by_table
            and "feature_flags" not in columns_by_table["stores"]
        ):
            await conn.execute(text("ALTER TABLE stores ADD COLUMN feature_flags JSON"))

        from modules.appointments.model import Appointment  # noqa: F401
        from modules.auth.session_model import AuthSession  # noqa: F401
        from modules.ledger.model import CustomerLedger  # noqa: F401
        from modules.otp.model import OtpVerification  # noqa: F401
        from modules.payments.model import (  # noqa: F401
            OutboxMessage,
            Payment,
            PaymentGatewayConfig,
            WebhookInbox,
        )
        from modules.services.model import Service  # noqa: F401
        from modules.staff.model import Schedule, Staff, StaffBlock  # noqa: F401
        from modules.stores.model import Store, StoreSchedule  # noqa: F401
        from modules.users.model import User  # noqa: F401

        await conn.run_sync(Base.metadata.create_all)

        if dialect_name == "sqlite":
            # The local runtime uses SQLite. We avoid destructive rebuilds here and
            # keep the bootstrap limited to additive changes only.
            return
