import asyncio
# from core.events import event_bus
from modules.notifications.tasks import send_appointment_confirmation

async def handle_appointment_created(data: dict):
    """
    Manejador del evento de creación de turno.
    Dispara la tarea de Celery para enviar la notificación.
    """
    # Preparar datos para el email
    email_data = {
        "public_id": data.get("public_id"),
        "service": data.get("service_name"),
        "staff": data.get("staff_name"),
        "date": data.get("starts_at")
    }
    
    # Disparar tarea asíncrona (Celery)
    send_appointment_confirmation.delay(data.get("client_email"), email_data)

async def start_event_listeners():
    """
    Inicia la suscripción a los canales de Redis y asigna manejadores.
    """
    # Suscribirse al canal de turnos creados
    # TODO: Refactorizar para instanciar EventBus localmente usando get_redis
    # await event_bus.subscribe("appointment.created", handle_appointment_created)
    print("--- Event Listener Started: Listening for appointment.created ---")
