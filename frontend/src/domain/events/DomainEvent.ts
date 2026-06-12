export interface EventPayload {
  eventName: string
  aggregateId: string
  occurredAt: string
  version: number
  payload: Record<string, unknown>
}

/**
 * Clase base abstracta de la cual extienden todos los Eventos de Dominio.
 * Todos los eventos son inmutables por diseño.
 */
export abstract class DomainEvent {
  public abstract readonly eventName: string
  public abstract readonly aggregateId: string
  public readonly occurredAt: Date
  public readonly version: number

  constructor(version = 1) {
    this.occurredAt = new Date()
    this.version = version
  }

  /**
   * Obtiene la carga útil específica de la subclase del evento.
   */
  public abstract getPayload(): Record<string, unknown>

  /**
   * Serializa el evento a un formato plano JSON amigable para auditorías o logs.
   */
  public toJSON(): EventPayload {
    return {
      eventName: this.eventName,
      aggregateId: this.aggregateId,
      occurredAt: this.occurredAt.toISOString(),
      version: this.version,
      payload: this.getPayload()
    }
  }
}
export default DomainEvent
