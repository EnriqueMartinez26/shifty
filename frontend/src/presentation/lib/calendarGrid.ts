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

/** Primera franja de la columna de horas. */
const GRID_START_MINUTES = 4 * 60
const SLOT_MINUTES = 15
/** Alto de cada franja: el mismo `h-16` que dibuja la columna de horas. */
export const SLOT_HEIGHT_PX = 64

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
 * Un instante ilegible cae al tope de la grilla con la altura minima, en vez
 * de emitir un `NaN` que el navegador descarta en silencio.
 */
export const gridPlacement = (
  startIso: string,
  endIso: string,
  minDurationMinutes = 0
): GridPlacement => {
  const minHeight = `${SLOT_HEIGHT_PX}px`
  const startMinutes = argentinaMinutesOfDay(startIso)
  const endMinutes = argentinaMinutesOfDay(endIso)
  if (startMinutes === null || endMinutes === null) return { top: '0px', height: minHeight }

  const offsetMinutes = startMinutes - GRID_START_MINUTES
  const durationMinutes = Math.max(endMinutes - startMinutes, minDurationMinutes)
  return {
    top: `${Math.max(offsetMinutes / SLOT_MINUTES, 0) * SLOT_HEIGHT_PX}px`,
    height: `${Math.max((durationMinutes / SLOT_MINUTES) * SLOT_HEIGHT_PX, SLOT_HEIGHT_PX)}px`
  }
}
