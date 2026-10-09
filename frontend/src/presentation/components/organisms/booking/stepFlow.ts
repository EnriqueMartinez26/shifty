interface StepOptions {
  /** Servicios publicados por la tienda (undefined mientras carga). */
  services: ReadonlyArray<{ public_id: string }> | undefined
}

interface StepJump {
  step: number
  /** Seleccion que hay que aplicar al saltear el paso trivial. */
  serviceId?: string
}

const STEP_SERVICE = 0
const STEP_DATETIME = 1

/**
 * Un paso con una sola opcion no es una eleccion: se elige solo y se saltea.
 * En el wizard de 3 pasos el unico salteable es el del servicio (el
 * profesional ya no es un paso: es un filtro dentro del horario, con
 * "Cualquiera" como opcion valida aunque haya uno solo).
 *
 * Mientras la lista carga (undefined) no se saltea nada: el paso se muestra
 * con su propio "Cargando".
 */
export const resolveStepJump = (from: number, options: StepOptions): StepJump => {
  if (from !== STEP_SERVICE) return { step: from }
  const unico = options.services?.length === 1 ? options.services[0] : undefined
  if (!unico) return { step: from }
  return { step: STEP_DATETIME, serviceId: unico.public_id }
}

/**
 * Volver atras hacia un paso que se salteo no tiene sentido: con un solo
 * servicio, "atras" desde el horario se queda donde esta.
 */
export const resolveBackJump = (from: number, options: StepOptions): number => {
  const step = Math.max(from - 1, STEP_SERVICE)
  if (step === STEP_SERVICE && options.services?.length === 1) return from
  return step
}

const STEP_CONFIRMATION = 2
const STEP_PARAM = 'step'

/**
 * `?step=` de la URL (F4-15): un entero no negativo, con tope en el ultimo
 * paso. Ausente o ilegible es `null`: el wizard usa su paso de arranque.
 */
export const parseStepParam = (raw: string | null): number | null => {
  const value = raw?.trim()
  if (!value || !/^\d+$/.test(value)) return null
  return Math.min(Number(value), STEP_CONFIRMATION)
}

/**
 * Un paso solo se muestra si lo anterior esta elegido: tras recargar con
 * ?step=2 el estado del wizard esta vacio y se cae al paso que corresponde
 * (sin servicio, el servicio; sin horario, el horario). Mandar los datos sin
 * horario armaria una reserva con `starts_at` vacio.
 */
export const clampStep = (
  step: number,
  chosen: { serviceId: string | null; startsAt: string | null }
): number => {
  if (step >= STEP_CONFIRMATION && chosen.serviceId && chosen.startsAt) return STEP_CONFIRMATION
  if (step >= STEP_DATETIME && chosen.serviceId) return STEP_DATETIME
  return STEP_SERVICE
}

/**
 * Copia de los parametros con el paso escrito; no toca `payment_id`,
 * `service`, `staff` ni `date`. El paso de arranque no se escribe (la URL
 * queda como llego), asi que volver al servicio desde un deep-link, que
 * arranca en el horario, deja `?step=0` explicito.
 */
export const withStepParam = (
  params: URLSearchParams,
  step: number,
  startStep: number
): URLSearchParams => {
  const next = new URLSearchParams(params)
  if (step === startStep) next.delete(STEP_PARAM)
  else next.set(STEP_PARAM, String(step))
  return next
}

export const readStepParam = (params: URLSearchParams): number | null =>
  parseStepParam(params.get(STEP_PARAM))
