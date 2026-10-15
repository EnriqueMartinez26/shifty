from typing import Sequence

from modules.services.model import Service, ServiceAddon
from modules.services.repository import ServiceRepository
from modules.services.schemas import ServiceAddonResponse, ServiceCatalogResponse


def to_service_response(
    service: Service, addons: Sequence[ServiceAddon] = ()
) -> ServiceCatalogResponse:
    response = ServiceCatalogResponse.model_validate(service)
    response.addons = [ServiceAddonResponse.model_validate(a) for a in addons]
    return response


async def to_service_responses(
    repo: ServiceRepository, store_id: str, services: Sequence[Service]
) -> list[ServiceCatalogResponse]:
    """Servicios con sus adicionales: una sola consulta para todos (regla 12)."""
    addons = await repo.addons_for(store_id, [service.id for service in services])
    return [to_service_response(s, addons.get(s.id, ())) for s in services]
