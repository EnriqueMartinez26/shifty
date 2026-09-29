/** Unica lista de estados conocidos: el tipo se deriva de aca. */
const BOOKING_STATUSES = [
  'pending',
  'pending_payment',
  'confirmed',
  'completed',
  'cancelled',
  'absent',
  'expired'
] as const

export type BookingStatusValue = (typeof BOOKING_STATUSES)[number]

/**
 * Estados absorbentes del turno.
 *
 * Replica el conjunto derivado de ALLOWED_STATUS_TRANSITIONS en el backend
 * (infrastructure/persistence/models/appointment.py). La equivalencia es un
 * contrato manual, ningun test lee los dos lados:
 * - test_el_conjunto_de_estados_terminales_es_el_documentado (backend) compara
 *   el grafo contra una constante Python propia; si el backend cambia sus
 *   terminales, su CI falla y el mensaje pide actualizar esta lista.
 * - BookingStatus.test.ts (columna "cobrable") congela esta lista del lado
 *   del front; si alguien la edita, falla ese test.
 * Cambiar un lado exige cambiar el otro a mano.
 */
const TERMINAL_STATUSES: readonly BookingStatusValue[] = [
  'completed',
  'cancelled',
  'absent',
  'expired'
]

/**
 * Un estado que el front conoce. El backend puede sumar uno antes que el
 * front: ese valor no se rechaza (la agenda no se cae), se muestra crudo y
 * sin acciones.
 */
export const isBookingStatus = (value: string): value is BookingStatusValue =>
  (BOOKING_STATUSES as readonly string[]).includes(value)

const isTerminalStatus = (value: string): boolean =>
  (TERMINAL_STATUSES as readonly string[]).includes(value)

/** Se le puede cobrar: un estado conocido que todavia no termino. */
export const isCollectibleStatus = (value: string): boolean =>
  isBookingStatus(value) && !isTerminalStatus(value)

export type BookingAction = 'confirm' | 'release' | 'cancel' | 'complete' | 'absent' | 'reschedule'

interface BookingActionContext {
  /** El turno ya empezo o termino: solo entonces se puede completar o marcar ausente. */
  hasStarted: boolean
  /** Puede liberar un turno pendiente (anula el link de pago). */
  canRelease: boolean
  /** Puede confirmar, completar o marcar ausente. */
  canManage: boolean
  /**
   * Puede cancelar o reprogramar ESTE turno (D-20260929-03): administracion y
   * recepcion, cualquiera; el profesional, solo los de su agenda.
   */
  canCancelOrReschedule: boolean
}

const isPendingStatus = (status: string): boolean =>
  status === 'pending' || status === 'pending_payment'

/**
 * Transiciones que la agenda ofrece para un turno, segun el grafo del backend:
 * - pendiente -> confirmar; pendiente o pendiente de pago -> "Liberar" para
 *   quien puede liberar y, si no, "Cancelar" (D-20260929-06);
 * - confirmado que no empezo -> cancelar; ya empezado -> completar o ausente
 *   (uno que empezo no se cancela, D-20260929-05);
 * - pendiente o confirmado -> reprogramar (un pendiente de pago no se mueve:
 *   409 DEPOSIT_PENDING_RESCHEDULE_DENIED).
 * Un estado terminal o desconocido no ofrece nada.
 */
export const bookingActionsFor = (
  status: string,
  { hasStarted, canRelease, canManage, canCancelOrReschedule }: BookingActionContext
): BookingAction[] => {
  const actions: BookingAction[] = []
  const canCancelNow = canCancelOrReschedule && !hasStarted
  if (status === 'pending' && canManage) actions.push('confirm')
  if (isPendingStatus(status)) {
    if (canRelease) actions.push('release')
    else if (canCancelNow) actions.push('cancel')
  }
  if (status === 'confirmed' && canCancelNow) actions.push('cancel')
  if (status === 'confirmed' && hasStarted && canManage) actions.push('complete', 'absent')
  if ((status === 'pending' || status === 'confirmed') && canCancelOrReschedule) {
    actions.push('reschedule')
  }
  return actions
}
