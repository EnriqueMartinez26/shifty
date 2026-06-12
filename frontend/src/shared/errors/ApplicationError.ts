export interface ErrorResponse {
  name: string
  message: string
  code: string
  statusCode: number
  isOperational: boolean
  context?: Record<string, unknown>
  stack?: string
}

/**
 * Clase base para todas las excepciones del frontend de la aplicación.
 * Define la estructura para un manejo unificado y tipado estricto de errores.
 */
export abstract class ApplicationError extends Error {
  public abstract readonly code: string
  public abstract readonly statusCode: number
  public abstract readonly isOperational: boolean
  public readonly context?: Record<string, unknown>

  constructor(message: string, context?: Record<string, unknown>) {
    super(message)
    this.name = this.constructor.name
    this.context = context
    Object.setPrototypeOf(this, new.target.prototype) // Reestablece la cadena de prototipos

    if ((Error as any).captureStackTrace) {
      ;(Error as any).captureStackTrace(this, this.constructor)
    }
  }

  /**
   * Serializa el error a una respuesta JSON limpia para logging o depuración.
   */
  public toJSON(): ErrorResponse {
    return {
      name: this.name,
      message: this.message,
      code: this.code,
      statusCode: this.statusCode,
      isOperational: this.isOperational,
      context: this.context,
      stack: this.stack
    }
  }
}
export default ApplicationError
