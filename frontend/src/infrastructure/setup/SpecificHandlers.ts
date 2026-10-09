import {
  ValidationError,
  NotFoundError,
  UnauthorizedError,
  ForbiddenError,
  ConflictError,
  InternalServerError,
  NetworkError,
  PaymentRequiredError,
  RateLimitError,
  RequestTimeoutError,
  ServiceUnavailableError,
  type ApplicationError
} from '@shared/errors'
import { ERROR_CODE_MESSAGES } from '@shared/errors/errorCodes'
import { ErrorHandler } from '@shared/errors/ErrorHandler'
import { getErrorCode, getRetryAfterSeconds } from '@shared/errors/getErrorMessage'

export type ToastKind = 'error' | 'warning' | 'info'
type ToastSink = (message: string, kind: ToastKind) => void

// Sin renderer conectado (tests, arranque) el aviso queda en consola.
let toastSink: ToastSink = (message, kind) => {
  console.warn(`[Toast ${kind.toUpperCase()}]: ${message}`)
}

/**
 * Puerto de avisos: main.tsx lo conecta a sonner (FF-17, D-20260928-07).
 * Infrastructure no importa presentation ni React (regla 25).
 */
export const setToastSink = (sink: ToastSink): void => {
  toastSink = sink
}

const showToast = (message: string, kind: ToastKind) => toastSink(message, kind)

/**
 * Texto de la tabla de codigos o el neutro de la pantalla. Un handler global
 * no sabe en que contexto aparece el error: nunca muestra el texto del
 * servidor, ni siquiera el de un 4xx (regla 20).
 */
const tableMessage = (error: unknown, fallback: string): string =>
  ERROR_CODE_MESSAGES.get(getErrorCode(error) ?? '') ?? fallback

const SECONDS_PER_MINUTE = 60

/** "Probá de nuevo en 12 s." / "en 10 min." a partir de Retry-After (F4-04). */
const retryHint = (error: unknown): string => {
  const seconds = getRetryAfterSeconds(error)
  if (seconds === undefined) return ''
  const wait =
    seconds <= 90 ? `${Math.ceil(seconds)} s` : `${Math.ceil(seconds / SECONDS_PER_MINUTE)} min`
  return ` Probá de nuevo en ${wait}.`
}

export class ValidationErrorHandler extends ErrorHandler {
  public canHandle(error: unknown): boolean {
    return error instanceof ValidationError
  }

  public async handle(error: ValidationError): Promise<void> {
    showToast(tableMessage(error, 'Hay datos incorrectos. Revisalos y volvé a intentar.'), 'error')
  }
}

export class NotFoundErrorHandler extends ErrorHandler {
  public canHandle(error: unknown): boolean {
    return error instanceof NotFoundError
  }

  public async handle(error: NotFoundError): Promise<void> {
    showToast(tableMessage(error, 'Lo que buscabas ya no existe. Actualizá la página.'), 'warning')
  }
}

export class UnauthorizedErrorHandler extends ErrorHandler {
  public canHandle(error: unknown): boolean {
    return error instanceof UnauthorizedError
  }

  /**
   * Solo avisa. Antes limpiaba el token y recargaba a /login con
   * `window.location.href`: esa recarga completa era lo unico que borraba el
   * cache de react-query al vencer la sesion, y ademas mandaba a /login a
   * cualquiera que viera un 401, tambien en el portal publico. Hoy el cliente
   * HTTP avisa `SESSION_EXPIRED_EVENT` y `AuthContext.resetSession()` limpia
   * perfil, token y TODO el cache (FF-26, D-20260928-05); `ProtectedRoute`
   * manda a /login recordando la ruta (FF-36).
   */
  public async handle(_error: UnauthorizedError): Promise<void> {
    showToast('Sesión expirada. Volvé a iniciar sesión.', 'info')
  }
}

export class ForbiddenErrorHandler extends ErrorHandler {
  public canHandle(error: unknown): boolean {
    return error instanceof ForbiddenError
  }

  public async handle(error: ForbiddenError): Promise<void> {
    // El backend tambien responde 403 cuando la funcion esta apagada por
    // feature flag (FeatureDisabledException): no es un problema de permisos.
    if (error.context?.errorCode === 'FEATURE_DISABLED') {
      showToast('Esta función no está habilitada para tu negocio.', 'info')
      return
    }
    showToast('No tenés permisos suficientes para realizar esta acción.', 'error')
  }
}

export class ConflictErrorHandler extends ErrorHandler {
  public canHandle(error: unknown): boolean {
    return error instanceof ConflictError
  }

  public async handle(error: ConflictError): Promise<void> {
    showToast(
      tableMessage(error, 'Los datos cambiaron mientras trabajabas. Actualizá y volvé a intentar.'),
      'warning'
    )
  }
}

export class InternalServerErrorHandler extends ErrorHandler {
  public canHandle(error: unknown): boolean {
    return error instanceof InternalServerError
  }

  public async handle(error: InternalServerError): Promise<void> {
    console.error('[SERVER CRITICAL ERROR]', error.toJSON())
    showToast('Error interno del servidor. Probá de nuevo más tarde.', 'error')
  }
}

export class NetworkErrorHandler extends ErrorHandler {
  public canHandle(error: unknown): boolean {
    return error instanceof NetworkError
  }

  public async handle(_error: NetworkError): Promise<void> {
    showToast('Sin conexión a Internet. Revisá tu conexión.', 'warning')
  }
}

/**
 * 402, 429, 502/503 y la lectura vencida (D-20260930-02): texto de la tabla de
 * codigos o uno neutro, nunca el del servidor.
 */
export class TransientErrorHandler extends ErrorHandler {
  public canHandle(error: unknown): boolean {
    return (
      error instanceof PaymentRequiredError ||
      error instanceof RateLimitError ||
      error instanceof ServiceUnavailableError ||
      error instanceof RequestTimeoutError
    )
  }

  public async handle(error: ApplicationError): Promise<void> {
    const fallback = 'No se pudo completar la acción. Probá de nuevo en unos minutos.'
    showToast(`${tableMessage(error, fallback)}${retryHint(error)}`, 'warning')
  }
}
