import { ApplicationError } from './ApplicationError'

/**
 * 502/503: el servicio (o una dependencia) no esta disponible por ahora. Es
 * operacional: reintentar mas tarde puede andar. El status real va en
 * `context.statusCode` y `context.retryAfter` trae los segundos si llegaron.
 */
export class ServiceUnavailableError extends ApplicationError {
  public readonly code = 'SERVICE_UNAVAILABLE_ERROR'
  public readonly statusCode = 503
  public readonly isOperational = true
}
