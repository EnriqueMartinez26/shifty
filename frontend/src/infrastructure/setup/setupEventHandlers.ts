import { AuditLogOnShiftCreated } from '../../application/handlers/AuditLogOnShiftCreated'
import { NotifyAdminsOnUserCreated } from '../../application/handlers/NotifyAdminsOnUserCreated'
import { SendWelcomeEmailOnUserCreated } from '../../application/handlers/SendWelcomeEmailOnUserCreated'
import type { EmailService } from '../../application/handlers/SendWelcomeEmailOnUserCreated'
import { EventBus } from '../../shared/events/EventBus'

type SetupServices = {
  emailService?: EmailService
}

/**
 * Suscribe y enlaza dinámicamente los handlers correspondientes al Bus de eventos.
 */
export function setupEventHandlers(eventBus: EventBus, services: SetupServices): void {
  // Evento: user.created
  if (services && services.emailService) {
    eventBus.subscribe('user.created', new SendWelcomeEmailOnUserCreated(services.emailService))
  }

  eventBus.subscribe('user.created', new NotifyAdminsOnUserCreated())

  // Evento: shift.created
  eventBus.subscribe('shift.created', new AuditLogOnShiftCreated())
}
export default setupEventHandlers
