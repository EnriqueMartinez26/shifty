import { EventHandler } from '../../shared/events/EventHandler';
import { UserCreatedEvent } from '../../domain/events/UserEvents';

export class NotifyAdminsOnUserCreated implements EventHandler<UserCreatedEvent> {
  public async handle(event: UserCreatedEvent): Promise<void> {
    console.log(
      `[Notificación Admin] Alerta: Nuevo usuario registrado con ID: ${event.aggregateId} y Rol: ${event.role.getValue()}`
    );
  }
}
export default NotifyAdminsOnUserCreated;
