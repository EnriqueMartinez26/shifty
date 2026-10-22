/**
 * Por que la cancelacion masiva no toco un turno, en palabras del dueno. Los
 * codigos son los del camino de cancelacion del panel; uno que el backend
 * sume despues cae en el generico y nunca se muestra crudo (regla 20).
 */
const SKIP_REASONS: ReadonlyMap<string, string> = new Map([
  ['APPOINTMENT_ALREADY_CANCELLED', 'Ya estaba cancelada.'],
  ['APPOINTMENT_ALREADY_STARTED', 'El turno ya empezó.'],
  ['APPOINTMENT_NOT_ACTIVE', 'El turno ya no está activo.'],
  // Un turno futuro que ya vencio no puede pasar a cancelado.
  ['INVALID_STATUS_TRANSITION', 'El turno ya no está activo.'],
  ['APPOINTMENT_NOT_FOUND', 'No la encontramos en esta tienda.'],
  ['NOT_FOUND', 'No la encontramos en esta tienda.']
])

export const bulkCancelSkipReason = (code: string): string =>
  SKIP_REASONS.get(code) ?? 'No se pudo cancelar.'
