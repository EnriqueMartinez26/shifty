from core.exceptions import PermissionDeniedException
from modules.users.model import User


def ensure_same_store(
    user: User, store_id: str | None, action: str = "operar sobre este recurso"
) -> None:
    if user.is_global_admin:
        return
    if store_id is None or str(user.store_id) != str(store_id):
        raise PermissionDeniedException(action)
