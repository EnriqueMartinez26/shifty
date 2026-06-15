import { EventHandler } from './EventHandler'
import { DomainEvent } from '../../domain/events/DomainEvent'

export type Unsubscribe = () => void

/**
 * Bus de eventos centralizado en memoria para coordinar la comunicación reactiva.
 * Implementa el patrón Observer con replay para historial de auditoría de eventos.
 */
export class EventBus {
  private static instance: EventBus
  private subscribers: Map<string, Set<EventHandler<DomainEvent>>> = new Map()
  private eventHistory: DomainEvent[] = []

  private constructor() {}

  /**
   * Obtiene la instancia única (Singleton) del EventBus.
   */
  public static getInstance(): EventBus {
    if (!EventBus.instance) {
      EventBus.instance = new EventBus()
    }
    return EventBus.instance
  }

  /**
   * Suscribe un EventHandler a un evento específico.
   * @returns Función de desuscripción limpia
   */
  public subscribe<T extends DomainEvent>(
    eventName: string,
    handler: EventHandler<T>
  ): Unsubscribe {
    if (!this.subscribers.has(eventName)) {
      this.subscribers.set(eventName, new Set())
    }

    this.subscribers.get(eventName)!.add(handler as EventHandler<DomainEvent>)

    return () => {
      const handlers = this.subscribers.get(eventName)
      if (handlers) {
        handlers.delete(handler)
        if (handlers.size === 0) {
          this.subscribers.delete(eventName)
        }
      }
    }
  }

  /**
   * Despacha un evento individual y ejecuta de forma asíncrona todos sus handlers asociados.
   */
  public async publish<T extends DomainEvent>(event: T): Promise<void> {
    this.eventHistory.push(event)
    const handlers = this.subscribers.get(event.eventName)

    if (!handlers || handlers.size === 0) {
      return
    }

    const executions = Array.from(handlers).map((handler) =>
      handler.handle(event).catch((err) => {
        console.error(
          `[EventBus] Error crítico al procesar handler en evento "${event.eventName}":`,
          err
        )
      })
    )

    await Promise.all(executions)
  }

  /**
   * Despacha por orden un array de eventos.
   */
  public async publishAll(events: DomainEvent[]): Promise<void> {
    for (const event of events) {
      await this.publish(event)
    }
  }

  /**
   * Retorna el historial completo de eventos despachados para auditoría (replay/logs).
   */
  public getHistory(): DomainEvent[] {
    return [...this.eventHistory]
  }

  /**
   * Restablece el historial de eventos e inscribe suscriptores (útil para testing).
   */
  public reset(): void {
    this.subscribers.clear()
    this.eventHistory = []
  }
}
export default EventBus
