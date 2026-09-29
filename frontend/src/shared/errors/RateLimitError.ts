import { ApplicationError } from './ApplicationError'

/** 429: demasiadas solicitudes. `context.retryAfter` trae los segundos si el server los mando. */
export class RateLimitError extends ApplicationError {
  public readonly code = 'RATE_LIMIT_ERROR'
  public readonly statusCode = 429
  public readonly isOperational = true
}
