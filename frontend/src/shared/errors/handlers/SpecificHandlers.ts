import { ErrorHandler } from '../ErrorHandler'
import {
  ValidationError,
  NotFoundError,
  UnauthorizedError,
  ForbiddenError,
  ConflictError,
  InternalServerError,
  NetworkError
} from '../index'

// Helper simulado para Toasts/Notificaciones en UI
const showToast = (message: string, type: 'error' | 'warning' | 'info') => {
  console.warn(`[Toast ${type.toUpperCase()}]: ${message}`)
}

export class ValidationErrorHandler extends ErrorHandler {
  public canHandle(error: unknown): boolean {
    return error instanceof ValidationError
  }

  public async handle(error: ValidationError): Promise<void> {
    const fields = error.context?.fields ? JSON.stringify(error.context.fields) : ''
    showToast(`Datos incorrectos: ${error.message} ${fields}`, 'error')
  }
}

export class NotFoundErrorHandler extends ErrorHandler {
  public canHandle(error: unknown): boolean {
    return error instanceof NotFoundError
  }

  public async handle(error: NotFoundError): Promise<void> {
    console.warn(`[Recurso No Encontrado]: ${error.message}`)
    showToast(error.message || 'El recurso solicitado no existe.', 'warning')
  }
}

export class UnauthorizedErrorHandler extends ErrorHandler {
  public canHandle(error: unknown): boolean {
    return error instanceof UnauthorizedError
  }

  public async handle(_error: UnauthorizedError): Promise<void> {
    showToast('Sesión expirada. Redirigiendo...', 'info')
    localStorage.removeItem('token') // Limpiar sesión
    window.location.href = '/login' // Redireccionar
  }
}

export class ForbiddenErrorHandler extends ErrorHandler {
  public canHandle(error: unknown): boolean {
    return error instanceof ForbiddenError
  }

  public async handle(_error: ForbiddenError): Promise<void> {
    showToast('No tienes permisos suficientes para realizar esta acción.', 'error')
  }
}

export class ConflictErrorHandler extends ErrorHandler {
  public canHandle(error: unknown): boolean {
    return error instanceof ConflictError
  }

  public async handle(error: ConflictError): Promise<void> {
    showToast(`Conflicto de datos: ${error.message}`, 'warning')
  }
}

export class InternalServerErrorHandler extends ErrorHandler {
  public canHandle(error: unknown): boolean {
    return error instanceof InternalServerError
  }

  public async handle(error: InternalServerError): Promise<void> {
    console.error('[SERVER CRITICAL ERROR]', error.toJSON())
    showToast('Error interno del servidor. Por favor, intenta de nuevo más tarde.', 'error')
  }
}

export class NetworkErrorHandler extends ErrorHandler {
  public canHandle(error: unknown): boolean {
    return error instanceof NetworkError
  }

  public async handle(_error: NetworkError): Promise<void> {
    showToast('Sin conexión a Internet. Verifica tu conectividad.', 'warning')
  }
}
