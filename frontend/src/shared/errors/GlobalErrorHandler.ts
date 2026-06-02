import { ErrorHandler } from './ErrorHandler';
import { ApplicationError } from './ApplicationError';
import { InternalServerError } from './InternalServerError';

/**
 * Orquestador principal encargado de evaluar cualquier excepción, buscar
 * el handler adecuado a través del Strategy Pattern y resolver la acción reactiva.
 */
export class GlobalErrorHandler {
  private handlers: ErrorHandler[] = [];

  /**
   * Registra una estrategia específica de manejo de errores.
   */
  public registerHandler(handler: ErrorHandler): void {
    this.handlers.push(handler);
  }

  /**
   * Procesa de forma asíncrona un error capturado.
   */
  public async handle(error: unknown): Promise<void> {
    // Buscar la primera estrategia que sea capaz de gestionar el error
    const suitableHandler = this.handlers.find((handler) => handler.canHandle(error));

    if (suitableHandler) {
      await suitableHandler.handle(error as ApplicationError);
      return;
    }

    // Fallback: Si no se encuentra un handler específico, tratar como error desconocido
    const fallbackError = new InternalServerError(
      error instanceof Error ? error.message : 'Unknown Application Error',
      { originalError: error }
    );
    
    console.error('[GlobalErrorHandler] Error sin manejador registrado capturado:', fallbackError.toJSON());
  }

  /**
   * Procesa un conjunto o lote de errores de manera paralela.
   */
  public async handleBatch(errors: unknown[]): Promise<void> {
    const executions = errors.map((err) => this.handle(err));
    await Promise.all(executions);
  }
}
export default GlobalErrorHandler;
