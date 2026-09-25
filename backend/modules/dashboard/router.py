from fastapi import Depends
from core.router import CanonicalAPIRouter
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_db
from core.roles import store_scope_for
from modules.auth.dependencies import get_current_staff
from modules.dashboard.repository import DashboardRepository
from modules.dashboard.schemas import DashboardSummaryResponse
from modules.dashboard.service import DashboardService
from modules.users.model import User

router = CanonicalAPIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary", response_model=DashboardSummaryResponse)
async def get_dashboard_summary(
    user: User = Depends(get_current_staff),
    db: AsyncSession = Depends(get_db),
) -> DashboardSummaryResponse:
    """Devuelve métricas resumidas y próximos turnos para el dashboard."""
    repository = DashboardRepository(db, store_id=store_scope_for(user))
    return await DashboardService(repository).get_summary()
