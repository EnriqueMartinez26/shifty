/**
 * Cuantos bloqueos genera una serie (FF-13, D-20260929-10).
 *
 * El backend expande desde el inicio sumando 1 o 7 dias y corta en
 * `recurrence_until` o en `max_occurrences` (tope 120), lo que llegue antes.
 * Antes el front mandaba siempre 5 y la serie se cortaba en silencio: ahora
 * se define por fecha de fin y se manda el N que sale de aca.
 *
 * `recurrence_until` viaja como la fecha de fin a la hora de FIN del bloqueo,
 * asi que el ultimo dia cuenta siempre. Las fechas son dias locales
 * `YYYY-MM-DD`: la cuenta es de calendario y no depende de la zona (regla 24).
 */

export type BlockRecurrence = 'none' | 'daily' | 'weekly'

/** Tope del backend (`max_occurrences`, `le=120`). */
export const MAX_BLOCK_OCCURRENCES = 120

const DAY_MS = 24 * 60 * 60 * 1000

const dayNumber = (value: string): number | null => {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value)
  if (!match) return null
  const [, year, month, day] = match
  const time = Date.UTC(Number(year), Number(month) - 1, Number(day))
  return Number.isNaN(time) ? null : Math.round(time / DAY_MS)
}

/**
 * `YYYY-MM-DD` corrido `days` dias de calendario; cadena vacia si no se lee.
 * La fecha de fin por defecto de una serie es el dia del bloqueo + 7.
 */
export const addCalendarDays = (date: string, days: number): string => {
  const day = dayNumber(date)
  if (day === null) return ''
  return new Date((day + days) * DAY_MS).toISOString().slice(0, 10)
}

/**
 * N sin recortar al tope: quien llama decide que hacer si pasa de 120.
 * 0 si la fecha de fin es anterior al inicio o alguna fecha no se lee.
 */
export const countOccurrences = (
  startDate: string,
  untilDate: string,
  recurrence: BlockRecurrence
): number => {
  if (recurrence === 'none') return 1
  const start = dayNumber(startDate)
  const until = dayNumber(untilDate)
  if (start === null || until === null || until < start) return 0
  const step = recurrence === 'daily' ? 1 : 7
  return Math.floor((until - start) / step) + 1
}
