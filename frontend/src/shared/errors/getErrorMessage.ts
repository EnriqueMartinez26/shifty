type ApiErrorLike = {
  message?: unknown
  response?: {
    data?: {
      detail?: unknown
      message?: unknown
      error_code?: unknown
    }
  }
}

/**
 * Errores de estado que necesitan una explicacion accionable.
 *
 * Ambos significan que la vista quedo desactualizada respecto del servidor:
 * el dato esta a salvo (el backend rechazo la operacion), pero el usuario
 * necesita saber que tiene que recargar en vez de ver un error crudo.
 */
const STATE_CONFLICT_MESSAGES: Record<string, string> = {
  INVALID_STATUS_TRANSITION:
    'El turno ya cambió de estado. Actualizá la agenda para ver cómo está ahora.',
  CONCURRENT_MODIFICATION:
    'Alguien más modificó este turno mientras lo editabas. Actualizá y volvé a intentar.',
  PAYMENT_APPOINTMENT_REQUIRES_RELEASE:
    'Este turno tiene un pago pendiente. Usá "Liberar" para soltarlo: así vence primero el link de pago.'
}

/** Indica si el error viene de un desfasaje de estado y conviene recargar. */
export const isStateConflictError = (error: unknown): boolean => {
  const code = (error as ApiErrorLike | undefined)?.response?.data?.error_code
  return typeof code === 'string' && code in STATE_CONFLICT_MESSAGES
}

export const getErrorMessage = (error: unknown, fallback: string): string => {
  const maybeError = error as ApiErrorLike | undefined
  const data = maybeError?.response?.data
  const code = data?.error_code

  if (typeof code === 'string' && STATE_CONFLICT_MESSAGES[code]) {
    return STATE_CONFLICT_MESSAGES[code]
  }

  const detail = data?.detail
  const message = data?.message ?? maybeError?.message

  if (typeof detail === 'string' && detail.trim()) return detail
  if (typeof message === 'string' && message.trim()) return message
  return fallback
}
