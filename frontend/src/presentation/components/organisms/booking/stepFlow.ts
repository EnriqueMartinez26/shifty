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
