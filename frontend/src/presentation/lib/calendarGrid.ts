/**
 * Geometria de la grilla de la vista dia del calendario.
 *
 * La columna de horas arranca a las 04:00 y avanza de a 15 minutos, 64px por
 * franja. Hasta 2026-09-18 la posicion de cada tarjeta se calculaba con
 * `getUTCHours()` del instante: un turno de 09:00 ART (12:00Z) se dibujaba
 * tres horas mas abajo, en la fila rotulada "12:00", mientras su propio texto
 * decia "09:00" (hora del navegador). La posicion y el rotulo salen ahora del
 * mismo dato: la hora de pared argentina.
 */

import { argentinaMinutesOfDay } from '@shared/utils/argentinaTime'

import { reportUnreadableInstant } from './reportUnreadableInstant'

/** Primera franja de la columna de horas. */
const GRID_START_MINUTES = 4 * 60
const SLOT_MINUTES = 15
/** Alto de cada franja, en px. La fila y la tarjeta salen de este mismo valor. */
export const SLOT_HEIGHT_PX = 64

/**
 * Cuantas franjas dibuja la columna. 48 x 15 min = 12 horas, o sea que la
 * grilla va de 04:00 a 15:45 y lo posterior no se dibuja. Es una limitacion
 * preexistente, no algo que introduzca este archivo: queda explicita aca en
 * vez de escondida en un `length: 48`.
 */
const GRID_SLOT_COUNT = 48

const pad = (value: number): string => String(value).padStart(2, '0')

/**
 * Rotulos de la columna de horas. Son aritmetica de reloj, no instantes: antes
 * salian de formatear un `Date` anclado a la medianoche local, lo que ataba el
 * rotulo a la zona del navegador sin necesidad.
 */
export const GRID_SLOT_LABELS: readonly string[] = Array.from(
  { length: GRID_SLOT_COUNT },
  (_, index) => {
    const minutes = GRID_START_MINUTES + index * SLOT_MINUTES
    return `${pad(Math.floor(minutes / 60))}:${pad(minutes % 60)}`
  }
)

/**
 * Piso de duracion visual de un turno: uno de 15 minutos quedaria demasiado
 * chico para leer el nombre del cliente y las acciones.
 */
export const MIN_APPOINTMENT_MINUTES = 30

export interface GridPlacement {
  top: string
  height: string
}

/**
 * Ubica un evento en la grilla a partir de sus instantes ISO.
 *
 * `minDurationMinutes` es el piso de duracion visual: los turnos pasan
 * `MIN_APPOINTMENT_MINUTES`, los bloqueos se dibujan con su duracion real.
 *
 * Devuelve `null` cuando algun instante es ilegible, y el llamador no lo
 * dibuja. Ubicarlo en `top: 0` lo apilaba encima de un turno legitimo anterior
 * a las 04:00, en columnas `position: absolute` sin orden garantizado: una
 * tarjeta con datos rotos tapando una real es peor que una ausente, sobre todo
 * porque la ausencia queda registrada en la telemetria.
 */
export const gridPlacement = (
  startIso: string,
  endIso: string,
  minDurationMinutes = 0
): GridPlacement | null => {
  const startMinutes = argentinaMinutesOfDay(startIso)
  const endMinutes = argentinaMinutesOfDay(endIso)
  if (startMinutes === null || endMinutes === null) {
    reportUnreadableInstant('calendarGrid', startMinutes === null ? startIso : endIso)
    return null
  }

  const offsetMinutes = startMinutes - GRID_START_MINUTES
  const durationMinutes = Math.max(endMinutes - startMinutes, minDurationMinutes)
  return {
    top: `${Math.max(offsetMinutes / SLOT_MINUTES, 0) * SLOT_HEIGHT_PX}px`,
    height: `${Math.max((durationMinutes / SLOT_MINUTES) * SLOT_HEIGHT_PX, SLOT_HEIGHT_PX)}px`
  }
}
