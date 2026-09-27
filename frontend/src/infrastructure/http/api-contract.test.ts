import {
  ConflictError,
  ForbiddenError,
  InternalServerError,
  NetworkError,
  NotFoundError,
  PaymentRequiredError,
  RateLimitError,
  ServiceUnavailableError,
  UnauthorizedError,
  ValidationError
} from '@shared/errors'

import { CanonicalApiError, normalizeApiError, unwrapApiEnvelope } from './api-contract'

describe('normalizeApiError', () => {
  it('maps canonical unauthorized responses to the shared unauthorized error type', () => {
    const error = normalizeApiError({
      response: {
        status: 401,
        data: {
          success: false,
          error_code: 'AUTH_REQUIRED',
          message: 'Sesión expirada',
          detail: { reason: 'token_expired' }
        }
      }
    })

    expect(error).toBeInstanceOf(UnauthorizedError)
    expect(error).toMatchObject({
      message: 'Sesión expirada',
      statusCode: 401,
      context: {
        errorCode: 'AUTH_REQUIRED',
        detail: { reason: 'token_expired' }
      }
    })
  })

  it('maps canonical validation and not-found responses to specific shared errors', () => {
    const validationError = normalizeApiError({
      response: {
        status: 422,
        data: {
          success: false,
          error_code: 'VALIDATION_ERROR',
          message: 'Datos inválidos',
          detail: { fields: { email: ['required'] } }
        }
      }
    })

    const notFoundError = normalizeApiError({
      response: {
        status: 404,
        data: {
          success: false,
          error_code: 'NOT_FOUND',
          message: 'Recurso no encontrado'
        }
      }
    })

    expect(validationError).toBeInstanceOf(ValidationError)
    expect(validationError).toMatchObject({
      message: 'Datos inválidos',
      context: {
        errorCode: 'VALIDATION_ERROR',
        detail: { fields: { email: ['required'] } }
      }
    })

    expect(notFoundError).toBeInstanceOf(NotFoundError)
    expect(notFoundError).toMatchObject({
      message: 'Recurso no encontrado',
      context: {
        errorCode: 'NOT_FOUND'
      }
    })
  })

  it('maps missing transport responses to the shared network error', () => {
    const error = normalizeApiError({
      code: 'ERR_NETWORK',
      message: 'Network Error'
    })

    expect(error).toBeInstanceOf(NetworkError)
    expect(error).toMatchObject({
      statusCode: 0,
      context: {
        originalError: {
          code: 'ERR_NETWORK',
          message: 'Network Error'
        }
      }
    })
  })

  it('keeps conflict responses explicit for retry-safe writes', () => {
    const error = normalizeApiError({
      response: {
        status: 409,
        data: {
          success: false,
          error_code: 'ALREADY_EXISTS',
          message: 'El turno ya fue tomado'
        }
      }
    })

    expect(error).toBeInstanceOf(ConflictError)
    expect(error).toMatchObject({
      message: 'El turno ya fue tomado',
      context: {
        errorCode: 'ALREADY_EXISTS'
      }
    })
  })

  it('maps forbidden and fallback server errors to the correct shared errors', () => {
    const forbiddenError = normalizeApiError({
      response: {
        status: 403,
        data: {
          success: false,
          error_code: 'FORBIDDEN',
          message: 'No tenés acceso'
        }
      }
    })

    const internalError = normalizeApiError({
      response: {
        status: 500,
        data: {
          success: false,
          error_code: 'SERVER_ERROR',
          detail: 'stack-trace'
        }
      }
    })

    expect(forbiddenError).toBeInstanceOf(ForbiddenError)
    expect(forbiddenError).toMatchObject({
      message: 'No tenés acceso',
      context: {
        errorCode: 'FORBIDDEN',
        statusCode: 403
      }
    })

    expect(internalError).toBeInstanceOf(InternalServerError)
    expect(internalError.message).toBe('stack-trace')
    expect(internalError).toMatchObject({
      context: {
        errorCode: 'SERVER_ERROR',
        detail: 'stack-trace',
        statusCode: 500
      }
    })
  })
})

describe('normalizeApiError: 402, 429 y 502/503 ya no son un 500', () => {
  const envelope = (errorCode: string, message: string, detail?: unknown) => ({
    success: false,
    error_code: errorCode,
    message,
    detail
  })

  it('un 402 es PaymentRequiredError operacional con su codigo', () => {
    const error = normalizeApiError({
      response: {
        status: 402,
        data: envelope('SUBSCRIPTION_SUSPENDED', 'Tu suscripcion esta suspendida')
      }
    })

    expect(error).toBeInstanceOf(PaymentRequiredError)
    expect(error).toMatchObject({
      isOperational: true,
      context: { errorCode: 'SUBSCRIPTION_SUSPENDED', statusCode: 402 }
    })
  })

  it('un 429 es RateLimitError y conserva el Retry-After en segundos', () => {
    const error = normalizeApiError({
      response: {
        status: 429,
        headers: { 'retry-after': '42' },
        data: envelope('RATE_LIMITED', 'Demasiadas solicitudes')
      }
    })

    expect(error).toBeInstanceOf(RateLimitError)
    expect(error).toMatchObject({
      isOperational: true,
      context: { errorCode: 'RATE_LIMITED', statusCode: 429, retryAfter: 42 }
    })
  })

  it('sin header, toma el retry_after del detail de RateLimitException', () => {
    const error = normalizeApiError({
      response: { status: 429, data: envelope('RATE_LIMITED', 'Espera', { retry_after: 30 }) }
    })

    expect(error.context).toMatchObject({ retryAfter: 30 })
  })

  it('un Retry-After que no son segundos se descarta', () => {
    const error = normalizeApiError({
      response: {
        status: 429,
        headers: { 'retry-after': 'Wed, 21 Oct 2026 07:28:00 GMT' },
        data: envelope('RATE_LIMITED', 'Espera')
      }
    })

    expect(error.context?.retryAfter).toBeUndefined()
  })

  it.each([502, 503])('un %i es ServiceUnavailableError con el status real', (status) => {
    const error = normalizeApiError({
      response: {
        status,
        headers: { 'retry-after': '5' },
        data: envelope('RATE_LIMIT_UNAVAILABLE', 'Limitador caido')
      }
    })

    expect(error).toBeInstanceOf(ServiceUnavailableError)
    expect(error).toMatchObject({
      isOperational: true,
      context: { statusCode: status, retryAfter: 5 }
    })
  })

  it('un error ya normalizado pasa tal cual, tambien las clases nuevas', () => {
    const original = new RateLimitError('ya normalizado', { retryAfter: 3 })

    expect(normalizeApiError(original)).toBe(original)
  })
})

describe('unwrapApiEnvelope', () => {
  it('unwraps success envelopes and leaves raw payloads untouched', () => {
    expect(unwrapApiEnvelope({ success: true, data: { id: 'one' } }, 200)).toEqual({
      id: 'one'
    })
    expect(unwrapApiEnvelope({ id: 'raw' }, 200)).toEqual({ id: 'raw' })
  })

  it('throws a canonical error for failed envelopes', () => {
    expect(() =>
      unwrapApiEnvelope(
        {
          success: false,
          error_code: 'INVALID',
          message: 'Datos inválidos',
          detail: { field: 'email' }
        },
        422
      )
    ).toThrow(CanonicalApiError)
  })
})
