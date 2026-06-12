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
