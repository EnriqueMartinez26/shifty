import { EventHandler } from '../../shared/events/EventHandler';
import { ShiftCreatedEvent } from '../../domain/events/ShiftEvents';

export class AuditLogOnShiftCreated implements EventHandler<ShiftCreatedEvent> {
  public async handle(event: ShiftCreatedEvent): Promise<void> {
    const payload = event.getPayload();
    console.warn(
      `[Auditoría Log] Turno asignado exitosamente al Staff ID: ${payload.staffId} desde ${payload.startTime} hasta ${payload.endTime}`
    );
  }
}
export default AuditLogOnShiftCreated;
