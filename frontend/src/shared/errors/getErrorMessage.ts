import { ApplicationError } from './ApplicationError'
import { ERROR_CODE_MESSAGES } from './errorCodes'
import { NetworkError } from './NetworkError'

type CodeCarrier = { context?: { errorCode?: unknown } }
type WrappedError = CodeCarrier & { originalError?: unknown }

/**
 * Errores de estado: la vista quedo desactualizada respecto del servidor. El
 * dato esta a salvo (el backend rechazo la operacion), pero conviene recargar.
 */
const STATE_CONFLICT_CODES: ReadonlySet<string> = new Set([
  'INVALID_STATUS_TRANSITION',
  'CONCURRENT_MODIFICATION',
  'PAYMENT_APPOINTMENT_REQUIRES_RELEASE',
  'APPOINTMENT_ALREADY_STARTED',
  'APPOINTMENT_ALREADY_CANCELLED',
  'APPOINTMENT_NOT_ACTIVE'
])

/**
 * Codigos cuyo `message` del servidor NO llega al usuario aunque sea un 4xx:
 * VALIDATION_ERROR trae el texto crudo de Pydantic ("body -> email: value is
 * not a valid email address"), los otros dos son genericos de framework.
 */
const SERVER_TEXT_DENYLIST: ReadonlySet<string> = new Set([
  'VALIDATION_ERROR',
  'HTTP_ERROR',
  'INTERNAL_SERVER_ERROR'
])

const readCode = (value: unknown): string | undefined => {
  if (typeof value !== 'object' || value === null) return undefined
  const code = (value as CodeCarrier).context?.errorCode
  return typeof code === 'string' && code ? code : undefined
}

const originalOf = (error: unknown): unknown =>
  typeof error === 'object' && error !== null ? (error as WrappedError).originalError : undefined

/**
 * El `error_code` del backend. El cliente HTTP lo deja en `context.errorCode`;
 * BaseService envuelve lo que no es ApplicationError en un Error plano con el
 * original en `originalError`, asi que tambien se busca ahi.
 */
export const getErrorCode = (error: unknown): string | undefined =>
  readCode(error) ?? readCode(originalOf(error))

/** Indica si el error viene de un desfasaje de estado y conviene recargar. */
export const isStateConflictError = (error: unknown): boolean => {
  const code = getErrorCode(error)
  return code !== undefined && STATE_CONFLICT_CODES.has(code)
}

const asApplicationError = (error: unknown): ApplicationError | undefined => {
  if (error instanceof ApplicationError) return error
  const original = originalOf(error)
  return original instanceof ApplicationError ? original : undefined
}

/**
 * Status HTTP real del error (0 = sin respuesta), o undefined si no es un
 * ApplicationError. Las clases fijan uno (ValidationError = 400 aun para un
 * 422); el que vino del servidor esta en `context.statusCode`.
 */
export const getHttpStatus = (error: unknown): number | undefined => {
  const appError = asApplicationError(error)
  if (!appError) return undefined
  const status = appError.context?.statusCode
  return typeof status === 'number' ? status : appError.statusCode
}

/**
 * Segundos de `Retry-After` que el cliente HTTP dejo en `context.retryAfter`
 * (429, 502/503), o undefined si no llegaron o no son un numero positivo.
 */
export const getRetryAfterSeconds = (error: unknown): number | undefined => {
  const value = asApplicationError(error)?.context?.retryAfter
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : undefined
}

const serverMessageFor = (error: unknown, code: string | undefined): string | undefined => {
  const appError = asApplicationError(error)
  if (!appError || !appError.message.trim()) return undefined
  // Texto armado en el front ("No se pudo conectar con el servidor.").
  if (appError instanceof NetworkError) return appError.message
  const status = getHttpStatus(appError) ?? 0
  const isClientError = status >= 400 && status < 500
  if (!appError.isOperational || !isClientError) return undefined
  if (code !== undefined && SERVER_TEXT_DENYLIST.has(code)) return undefined
  return appError.message
}

/** El campo de una entrada "ruta -> del -> campo: motivo" del 422 de Pydantic. */
const fieldOf = (entry: unknown): string | undefined => {
  if (typeof entry !== 'string') return undefined
  const separator = entry.indexOf(': ')
  if (separator <= 0) return undefined
  const segments = entry
    .slice(0, separator)
    .split(' -> ')
    .map((segment) => segment.trim())
    .filter((segment) => segment && !/^\d+$/.test(segment))
  return segments[segments.length - 1]
}

/**
 * Campos que el backend rechazo en un 422 de Pydantic. El handler de main.py
 * deja en `detail` una lista "ruta -> campo: motivo" (sin "body"); se toma el
 * ultimo tramo de la ruta, salteando indices de lista. Un `detail` que no es
 * lista (ValidationException de negocio) no nombra campos. El motivo no se
 * usa: es texto crudo de Pydantic, en ingles (regla 20).
 */
export const getInvalidFields = (error: unknown): string[] => {
  if (getErrorCode(error) !== 'VALIDATION_ERROR') return []
  const detail = asApplicationError(error)?.context?.detail
  if (!Array.isArray(detail)) return []
  return detail.map(fieldOf).filter((field): field is string => field !== undefined)
}

const fieldMessageFor = (
  error: unknown,
  fieldMessages: Partial<Record<string, string>>
): string | undefined => {
  for (const field of getInvalidFields(error)) {
    const message = Object.hasOwn(fieldMessages, field) ? fieldMessages[field] : undefined
    if (message) return message
  }
  return undefined
}

/**
 * Texto para mostrarle al usuario, en este orden:
 * 1. `overrides[code]`: la pantalla sabe decirlo mejor.
 * 2. `fieldMessages[campo]`: en un 422, el texto de la pantalla para el
 *    primer campo rechazado que conoce.
 * 3. La tabla de codigos (errorCodes.ts).
 * 4. El mensaje del servidor, solo si es un 4xx operacional y su codigo no
 *    esta en la lista negra (regla 20: nada crudo ni tecnico).
 * 5. `fallback`.
 */
export const getErrorMessage = (
  error: unknown,
  fallback: string,
  overrides: Partial<Record<string, string>> = {},
  fieldMessages: Partial<Record<string, string>> = {}
): string => {
  const code = getErrorCode(error)
  if (code !== undefined) {
    const override = Object.hasOwn(overrides, code) ? overrides[code] : undefined
    const known = override ?? fieldMessageFor(error, fieldMessages) ?? ERROR_CODE_MESSAGES.get(code)
    if (known) return known
  }
  return serverMessageFor(error, code) ?? fallback
}
