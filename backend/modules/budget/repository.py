from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from modules.budget.model import Budget


def _compute_total(estimated_hours: float, hourly_rate: float) -> float:
    total = Decimal(str(estimated_hours)) * Decimal(str(hourly_rate))
    return float(total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


class BudgetRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, payload: dict, store_id: int) -> Budget:
        total_cost = _compute_total(payload["estimated_hours"], payload["hourly_rate"])
        budget = Budget(**payload, store_id=store_id, total_cost=total_cost)
        self.db.add(budget)
        await self.db.commit()
        await self.db.refresh(budget)
        return budget

    async def list(self, include_inactive: bool = False) -> list[Budget]:
        query = select(Budget)
        if not include_inactive:
            query = query.where(Budget.is_active.is_(True))
        query = query.order_by(Budget.created_at.desc())
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def get_by_public_id(self, public_id: str) -> Budget | None:
        result = await self.db.execute(select(Budget).where(Budget.public_id == public_id))
        return result.scalar_one_or_none()

    async def update(self, budget: Budget, payload: dict) -> Budget:
        for key, value in payload.items():
            if value is not None:
                setattr(budget, key, value)

        if payload.get("estimated_hours") is not None or payload.get("hourly_rate") is not None:
            budget.total_cost = _compute_total(float(budget.estimated_hours), float(budget.hourly_rate))

        await self.db.commit()
        await self.db.refresh(budget)
        return budget

    async def soft_delete(self, budget: Budget) -> None:
        budget.is_active = False
        await self.db.commit()
