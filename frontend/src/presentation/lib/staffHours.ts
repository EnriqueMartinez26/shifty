/**
 * Horario efectivo de cada profesional en la vista dia (FF-03).
 *
 * Misma regla que el backend (`appointments/working_hours.py`,
 * D-20260929-01): la agenda usa las franjas del profesional; uno SIN ninguna
 * franja cargada (ningun dia) atiende en el horario comercial del local, y uno
 * con franjas pero ninguna ese dia no atiende ese dia. Aca solo se DIBUJA: la
 * validacion la hace el backend (409 `OUT_OF_SCHEDULE`).
 */

import type { StaffSchedule } from '@domain/entities/Staff'

import {
  SLOT_HEIGHT_PX,
  SLOT_MINUTES,
  parseHhMm,
  type DayGrid,
  type TimeRange
} from './calendarGrid'

/** Claves de `business_hours` por dia de la semana del backend (0 = lunes). */
const BUSINESS_HOURS_DAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const

type BusinessHours = Readonly<Record<string, readonly { open: string; close: string }[]>>

interface OffHoursSegment {
  topPx: number
  heightPx: number
}

/** Dia de la semana como lo cuenta el backend: 0 = lunes ... 6 = domingo. */
export const mondayBasedWeekday = (date: Date): number => (date.getDay() + 6) % 7

const toRange = (start: string, end: string): TimeRange[] => {
  const startMinutes = parseHhMm(start)
  const endMinutes = parseHhMm(end)
  if (startMinutes === null || endMinutes === null || endMinutes <= startMinutes) return []
  return [{ startMinutes, endMinutes }]
}

/**
 * Horario comercial del local ese dia. `null` = todavia no se sabe (la ficha
 * no cargo): no es lo mismo que un dia cerrado, que devuelve `[]`.
 */
export const storeRangesFor = (
  businessHours: BusinessHours | undefined,
  weekday: number
): TimeRange[] | null => {
  if (!businessHours) return null
  const periods = businessHours[BUSINESS_HOURS_DAY_KEYS[weekday] ?? ''] ?? []
  return periods.flatMap((period) => toRange(period.open, period.close))
}

/**
 * Franjas en que el profesional atiende ese dia. `null` solo cuando cae al
 * horario del local y ese horario todavia no se conoce.
 */
export const workingRangesFor = (
  schedules: readonly StaffSchedule[],
  weekday: number,
  storeRanges: TimeRange[] | null
): TimeRange[] | null => {
  if (schedules.length === 0) return storeRanges
  return schedules
    .filter((row) => row.dayOfWeek === weekday)
    .flatMap((row) => toRange(row.startTime, row.endTime))
}

const minutesToPx = (minutes: number) => (minutes / SLOT_MINUTES) * SLOT_HEIGHT_PX

/**
 * Tramos de las bandas abiertas de la grilla que quedan FUERA de las franjas
 * del profesional, en px. Las bandas cerradas ya se pintan como "Cerrado".
 */
export const offHoursSegments = (
  grid: DayGrid,
  working: readonly TimeRange[]
): OffHoursSegment[] => {
  const sorted = [...working].sort((left, right) => left.startMinutes - right.startMinutes)
  const segments: OffHoursSegment[] = []
  for (const band of grid.bands) {
    if (band.kind !== 'open') continue
    let cursor = band.startMinutes
    const emitUntil = (end: number) => {
      if (end > cursor) {
        segments.push({
          topPx: band.topPx + minutesToPx(cursor - band.startMinutes),
          heightPx: minutesToPx(end - cursor)
        })
      }
    }
    for (const range of sorted) {
      if (range.endMinutes <= cursor || range.startMinutes >= band.endMinutes) continue
      emitUntil(Math.min(range.startMinutes, band.endMinutes))
      cursor = Math.max(cursor, range.endMinutes)
      if (cursor >= band.endMinutes) break
    }
    emitUntil(band.endMinutes)
  }
  return segments
}
