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

export type BookingAction = 'confirm' | 'release' | 'complete' | 'absent'

interface BookingActionContext {
  /** El turno ya empezo o termino: solo entonces se puede completar o marcar ausente. */
  hasStarted: boolean
  /** Puede liberar un turno pendiente (anula el link de pago). */
  canRelease: boolean
  /** Puede confirmar, completar o marcar ausente. */
  canManage: boolean
}

/**
 * Transiciones que la agenda ofrece para un turno, segun el grafo del backend:
 * pendiente -> confirmar o liberar; pendiente de pago -> solo liberar (se
 * confirma con el pago); confirmado y ya empezado -> completar o ausente. Un
 * estado terminal o desconocido no ofrece nada.
 */
export const bookingActionsFor = (
  status: string,
  { hasStarted, canRelease, canManage }: BookingActionContext
): BookingAction[] => {
  const actions: BookingAction[] = []
  if (status === 'pending' && canManage) actions.push('confirm')
  if ((status === 'pending' || status === 'pending_payment') && canRelease) actions.push('release')
  if (status === 'confirmed' && hasStarted && canManage) actions.push('complete', 'absent')
  return actions
}
