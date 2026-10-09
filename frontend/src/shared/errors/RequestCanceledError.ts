import { ApplicationError } from './ApplicationError'

/**
 * Una lectura que cancelo quien la pidio: react-query aborta con su `signal`
 * la consulta que quedo reemplazada (otra busqueda, otro dia de la grilla).
 * No es una falla: no se registra como error, no se avisa ni se reintenta.
 * Un "Request aborted" de la red (ECONNABORTED) sigue siendo NetworkError.
 */
export class RequestCanceledError extends ApplicationError {
  public readonly code = 'REQUEST_CANCELED'
  public readonly statusCode = 0
  public readonly isOperational = true
}

/**
 * Tambien lo reconoce envuelto por BaseService en un Error plano, con el
 * original en `originalError`.
 */
export const isRequestCanceledError = (error: unknown): boolean => {
  if (error instanceof RequestCanceledError) return true
  if (typeof error !== 'object' || error === null) return false
  return (error as { originalError?: unknown }).originalError instanceof RequestCanceledError
}
