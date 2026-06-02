from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.validation import PUBLIC_ID_PATTERN
from modules.auth.dependencies import get_current_admin
from modules.budget.repository import BudgetRepository
from modules.budget.schemas import BudgetCreate, BudgetResponse, BudgetUpdate
from modules.users.model import User

router = APIRouter(prefix="/budget", tags=["Budget"])
PublicIdPath = Annotated[str, Path(min_length=1, max_length=64, pattern=PUBLIC_ID_PATTERN)]


@router.post("/", response_model=BudgetResponse, status_code=status.HTTP_201_CREATED)
async def create_budget(
    data: BudgetCreate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = BudgetRepository(db)
    return await repo.create(data.model_dump(), admin.store_id)


@router.get("/", response_model=list[BudgetResponse])
async def list_budgets(
    include_inactive: bool = Query(False),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = BudgetRepository(db)
    return await repo.list(include_inactive=include_inactive)


@router.get("/{public_id}", response_model=BudgetResponse)
async def get_budget(
    public_id: PublicIdPath,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = BudgetRepository(db)
    budget = await repo.get_by_public_id(public_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Presupuesto no encontrado")
    return budget


@router.patch("/{public_id}", response_model=BudgetResponse)
async def update_budget(
    public_id: PublicIdPath,
    data: BudgetUpdate,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = BudgetRepository(db)
    budget = await repo.get_by_public_id(public_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Presupuesto no encontrado")

    return await repo.update(budget, data.model_dump())


@router.delete("/{public_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_budget(
    public_id: PublicIdPath,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    repo = BudgetRepository(db)
    budget = await repo.get_by_public_id(public_id)
    if not budget:
        raise HTTPException(status_code=404, detail="Presupuesto no encontrado")
    await repo.soft_delete(budget)
