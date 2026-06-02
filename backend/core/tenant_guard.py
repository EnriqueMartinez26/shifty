from fastapi import HTTPException, status

from modules.users.model import User


def ensure_same_store(user: User, store_id: str | None, action: str = "operar sobre este recurso") -> None:
    if user.is_global_admin:
        return
    if store_id is None or str(user.store_id) != str(store_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No tenes permiso para {action}",
        )
