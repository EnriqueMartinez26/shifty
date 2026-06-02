import { ApplicationError } from './ApplicationError';

/**
 * Clase base que define las estrategias individuales de manejo de errores.
 */
export abstract class ErrorHandler {
  /**
   * Determina si este manejador específico puede procesar la excepción dada.
   */
  public abstract canHandle(error: unknown): boolean;

  /**
   * Procesa el error realizando tareas como logging, notificaciones al usuario,
   * limpiezas de estado o redirecciones.
   */
  public abstract handle(error: ApplicationError): Promise<void>;
}
export default ErrorHandler;
