import {
  ConflictError,
  ForbiddenError,
  InternalServerError,
  NetworkError,
  NotFoundError,
  UnauthorizedError,
  ValidationError,
  type ApplicationError
} from '@shared/errors'

export interface ApiSuccess<T> {
  success: true
  data: T
  meta?: Record<string, unknown>
}

export interface ApiErrorResponse {
  success: false
  error_code: string
  message: string
  detail?: unknown
}

export type ApiEnvelope<T> = ApiSuccess<T> | ApiErrorResponse

export type NormalizedApiErrorContext = {
  errorCode?: string
  detail?: unknown
  statusCode?: number
  originalError?: unknown
}

type ApiErrorLike = {
  response?: {
    status?: number
    data?: unknown
  }
  code?: string
  message?: unknown
}

export class CanonicalApiError extends Error {
  readonly errorCode: string
  readonly statusCode: number
  readonly detail?: unknown

  constructor(response: ApiErrorResponse, statusCode: number) {
    super(response.message)
    this.name = 'CanonicalApiError'
    this.errorCode = response.error_code
    this.statusCode = statusCode
    this.detail = response.detail
  }
}

export const isApiEnvelope = (value: unknown): value is ApiEnvelope<unknown> =>
  typeof value === 'object' &&
  value !== null &&
  'success' in value &&
  (value as { success?: unknown }).success !== undefined

export const unwrapApiEnvelope = <T>(value: T | ApiEnvelope<T>, statusCode: number): T => {
  if (!isApiEnvelope(value)) {
    return value as T
  }
  if (value.success) {
    return value.data as T
  }
  throw new CanonicalApiError(value, statusCode)
}

const isPlainObject = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

const asMessage = (value: unknown, fallback: string): string => {
  if (typeof value === 'string' && value.trim()) {
    return value
  }

  return fallback
}

const readLegacyMessage = (payload: unknown): string | undefined => {
  if (!isPlainObject(payload)) {
    return undefined
  }

  const candidateMessage = payload.message ?? payload.detail

  if (typeof candidateMessage === 'string' && candidateMessage.trim()) {
    return candidateMessage
  }

  return undefined
}

const readResponsePayload = (error: ApiErrorLike): ApiErrorResponse | undefined => {
  const payload = error.response?.data

  if (!isApiEnvelope(payload) || payload.success !== false) {
    return undefined
  }

  return payload
}

const buildContext = (
  response: ApiErrorResponse | undefined,
  error: ApiErrorLike,
  statusCode: number
): NormalizedApiErrorContext => ({
  errorCode: response?.error_code,
  detail: response?.detail,
  statusCode,
  originalError: {
    code: error.code,
    message: error.message,
    payload: response,
    statusCode
  }
})

const createMappedError = (
  statusCode: number,
  message: string,
  context: NormalizedApiErrorContext
): ApplicationError => {
  if (statusCode === 401) {
    return new UnauthorizedError(message, context)
  }

  if (statusCode === 403) {
    return new ForbiddenError(message, context)
  }

  if (statusCode === 404) {
    return new NotFoundError(message, context)
  }

  if (statusCode === 409) {
    return new ConflictError(message, context)
  }

  if (statusCode === 400 || statusCode === 422) {
    return new ValidationError(message, context)
  }

  return new InternalServerError(message, context)
}

export const normalizeApiError = (error: unknown): ApplicationError => {
  if (error instanceof NetworkError || error instanceof UnauthorizedError) {
    return error
  }

  if (error instanceof ConflictError || error instanceof ForbiddenError) {
    return error
  }

  if (error instanceof NotFoundError || error instanceof ValidationError) {
    return error
  }

  if (error instanceof InternalServerError) {
    return error
  }

  const maybeError = error as ApiErrorLike | undefined
  const statusCode = maybeError?.response?.status ?? 0

  if (!maybeError?.response) {
    return new NetworkError('No se pudo conectar con el servidor.', {
      originalError: {
        code: maybeError?.code,
        message: maybeError?.message,
        statusCode: 0
      }
    })
  }

  const payload = readResponsePayload(maybeError)
  const responseMessage = payload?.message ?? readLegacyMessage(maybeError.response?.data)
  const message = asMessage(
    responseMessage,
    asMessage(maybeError.message, 'No se pudo procesar la solicitud.')
  )
  const context = buildContext(payload, maybeError, statusCode)

  return createMappedError(statusCode, message, context)
}
