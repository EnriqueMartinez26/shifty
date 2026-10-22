/**
 * Diseño previo despues de pagar con Mercado Pago (S7, QA 2026-10-21).
 *
 * Con seña por MP el portal redirige al link de pago apenas reserva, asi que
 * la pantalla de exito (con el boton para mandar el diseño por WhatsApp)
 * nunca se ve. Antes de salir se guarda un resumen minimo del turno en
 * sessionStorage, que sobrevive la ida y vuelta a MP en la misma pestaña, y
 * la pantalla de vuelta lo usa para ofrecer el mismo boton.
 *
 * Solo lo que arma el mensaje: el primer nombre de la clienta (sin telefono
 * ni email), los servicios, el horario y el texto de la tienda. Sin storage,
 * o con un valor ilegible, no hay bloque y el resto sigue igual: nada de esto
 * tira.
 */

export interface PriorDesignHandoff {
  /** `public_id` del turno: la vuelta solo lo muestra para ese turno. */
  appointmentPublicId: string
  serviceName: string
  /** "Corte + Barba"; null en una respuesta vieja. */
  servicesLabel: string | null
  addons: { name: string; quantity: number }[]
  clientFirstName: string
  /** Instante UTC del turno, tal cual lo devolvio la API. */
  startsAt: string
  /** El mensaje de la tienda ya resuelto (el propio o el de siempre). */
  message: string
}

const storageKey = (storePublicId: string): string => `shifty:prior-design:${storePublicId}`

const isAddon = (value: unknown): value is { name: string; quantity: number } =>
  typeof value === 'object' &&
  value !== null &&
  typeof (value as { name?: unknown }).name === 'string' &&
  typeof (value as { quantity?: unknown }).quantity === 'number'

const isHandoff = (value: unknown): value is PriorDesignHandoff => {
  if (typeof value !== 'object' || value === null) return false
  const candidate = value as Record<string, unknown>
  return (
    typeof candidate.appointmentPublicId === 'string' &&
    typeof candidate.serviceName === 'string' &&
    (candidate.servicesLabel === null || typeof candidate.servicesLabel === 'string') &&
    Array.isArray(candidate.addons) &&
    candidate.addons.every(isAddon) &&
    typeof candidate.clientFirstName === 'string' &&
    typeof candidate.startsAt === 'string' &&
    typeof candidate.message === 'string'
  )
}

/** Guarda el resumen del turno de esta tienda; sin storage no hace nada. */
export const savePriorDesignHandoff = (
  storePublicId: string,
  handoff: PriorDesignHandoff
): void => {
  try {
    window.sessionStorage.setItem(storageKey(storePublicId), JSON.stringify(handoff))
  } catch {
    // sin storage o lleno: la vuelta no muestra el bloque
  }
}

/** El resumen guardado para ese turno de la tienda, o null. */
export const readPriorDesignHandoff = (
  storePublicId: string,
  appointmentPublicId: string
): PriorDesignHandoff | null => {
  let raw: string | null
  try {
    raw = window.sessionStorage.getItem(storageKey(storePublicId))
  } catch {
    return null
  }
  if (!raw) return null
  try {
    const parsed: unknown = JSON.parse(raw)
    return isHandoff(parsed) && parsed.appointmentPublicId === appointmentPublicId ? parsed : null
  } catch {
    // valor ilegible: como si no hubiera nada
    return null
  }
}
