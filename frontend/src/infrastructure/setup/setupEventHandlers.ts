import { EventBus } from '../../shared/events/EventBus';
import { SendWelcomeEmailOnUserCreated } from '../../application/handlers/SendWelcomeEmailOnUserCreated';
import { NotifyAdminsOnUserCreated } from '../../application/handlers/NotifyAdminsOnUserCreated';
import { AuditLogOnShiftCreated } from '../../application/handlers/AuditLogOnShiftCreated';

/**
 * Suscribe y enlaza dinámicamente los handlers correspondientes al Bus de eventos.
 */
export function setupEventHandlers(eventBus: EventBus, services: any): void {
  // Evento: user.created
  if (services && services.emailService) {
    eventBus.subscribe(
      'user.created',
      new SendWelcomeEmailOnUserCreated(services.emailService)
    );
  }
  
  eventBus.subscribe(
    'user.created',
    new NotifyAdminsOnUserCreated()
  );

  // Evento: shift.created
  eventBus.subscribe(
    'shift.created',
    new AuditLogOnShiftCreated()
  );
}
export default setupEventHandlers;
