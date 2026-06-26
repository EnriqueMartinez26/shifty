from modules.services.model import Service
from modules.services.schemas import ServiceResponse


def to_service_response(service: Service) -> ServiceResponse:
    return ServiceResponse.model_validate(service)
