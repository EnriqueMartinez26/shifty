import { DomainEvent } from '../../domain/events/DomainEvent';

/**
 * Interfaz genérica y con tipado estricto que deben implementar 
 * todos los suscriptores o manejadores de eventos.
 */
export interface EventHandler<T extends DomainEvent> {
  /**
   * Ejecuta la acción secundaria/side-effect cuando se despacha el evento.
   * @param event Instancia del evento de dominio
   */
  handle(event: T): Promise<void>;
}
export default EventHandler;
