export interface StepOptions {
  /** Servicios publicados por la tienda (undefined mientras carga). */
  services: ReadonlyArray<{ public_id: string }> | undefined
  /** Profesionales del servicio elegido (undefined mientras carga). */
  staff: ReadonlyArray<{ public_id: string }> | undefined
}

export interface StepJump {
  step: number
  /** Selecciones que hay que aplicar al saltear un paso trivial. */
  serviceId?: string
  staffId?: string
}

const STEP_SERVICE = 0
const STEP_STAFF = 1
const STEP_DATETIME = 2

/**
 * Un paso con una sola opcion no es una eleccion: se elige solo y se saltea.
 * Una tienda de una persona con un servicio pasa de cinco pasos a tres.
 *
 * Devuelve el paso al que hay que ir desde `from` y las selecciones que hay
 * que aplicar. Mientras las listas cargan (undefined) no se saltea nada: el
 * paso se muestra con su propio "Cargando".
 */
export const resolveStepJump = (from: number, options: StepOptions): StepJump => {
  const jump: StepJump = { step: from }

  if (jump.step === STEP_SERVICE) {
    const unico = options.services?.length === 1 ? options.services[0] : undefined
    if (!unico) return jump
    jump.serviceId = unico.public_id
    jump.step = STEP_STAFF
  }

  if (jump.step === STEP_STAFF) {
    const unico = options.staff?.length === 1 ? options.staff[0] : undefined
    if (!unico) return jump
    jump.staffId = unico.public_id
    jump.step = STEP_DATETIME
  }

  return jump
}

/**
 * Volver atras desde un paso que se salteo tiene que seguir de largo: si no,
 * el boton "atras" no hace nada visible.
 */
export const resolveBackJump = (from: number, options: StepOptions): number => {
  let step = Math.max(from - 1, STEP_SERVICE)
  if (step === STEP_STAFF && options.staff?.length === 1) step = STEP_SERVICE
  if (step === STEP_SERVICE && options.services?.length === 1) return from
  return step
}
