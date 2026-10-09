/**
 * Borrador de la semana de trabajo de un profesional (editor de horarios).
 *
 * Regla del backend (`appointments/working_hours.py`, D-20260929-01): un
 * profesional SIN ninguna franja atiende en el horario comercial del local;
 * uno con franjas atiende SOLO en ellas, y un dia sin franjas no atiende
 * aunque el local abra. Por eso el editor tiene dos modos: "usa el horario de
 * la tienda" (se guarda la lista vacia) y "horario propio" (se guarda la
 * semana). Un horario propio con todos los dias cerrados no existe: guardaria
 * la lista vacia y el profesional volveria al horario de la tienda.
 *
 * Las validaciones repiten las del backend para avisar antes de guardar; la
 * fuente de verdad sigue siendo el backend (`PUT /staff/{id}/schedules`).
 */

import type { StaffSchedule } from '@domain/entities/Staff'

import { getErrorCode, getErrorMessage } from '@shared/errors/getErrorMessage'

/**
 * Seis franjas por dia: `MAX_SCHEDULES_PER_WEEK = 42` en
 * `backend/modules/staff/schemas.py` (7 x 6).
 */
export const MAX_RANGES_PER_DAY = 6

/** Dias en el orden del backend: 0 = lunes ... 6 = domingo. */
export const WEEK_DAYS = [
  { label: 'Lunes', short: 'Lun' },
  { label: 'Martes', short: 'Mar' },
  { label: 'Miércoles', short: 'Mié' },
  { label: 'Jueves', short: 'Jue' },
  { label: 'Viernes', short: 'Vie' },
  { label: 'Sábado', short: 'Sáb' },
  { label: 'Domingo', short: 'Dom' }
] as const

/** Claves de `business_hours` del local, en el mismo orden que `WEEK_DAYS`. */
const BUSINESS_HOURS_DAY_KEYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const

/** Franja editable, en hora argentina `HH:MM` (lo que da un `<input type="time">`). */
export interface WeekRange {
  start: string
  end: string
}

/** Una lista de franjas por dia; lista vacia = ese dia no atiende. */
export type WeekDraft = readonly (readonly WeekRange[])[]

export type ScheduleMode = 'store' | 'own'

type BusinessHours = Readonly<Record<string, readonly { open: string; close: string }[]>>

/** Franja nueva por defecto al abrir un dia o agregar una franja. */
export const DEFAULT_RANGE: WeekRange = { start: '09:00', end: '18:00' }

const toHhMm = (value: string): string => value.slice(0, 5)

const emptyWeek = (): WeekRange[][] => WEEK_DAYS.map(() => [])

const byStart = (left: WeekRange, right: WeekRange) => left.start.localeCompare(right.start)

/** `ScheduleBase.validate_time_order`: inicio estrictamente antes del fin. */
const isValidRange = (range: WeekRange): boolean =>
  range.start !== '' && range.end !== '' && range.start < range.end

/** Semana guardada del profesional, ordenada por hora de inicio en cada dia. */
export const draftFromSchedules = (schedules: readonly StaffSchedule[]): WeekDraft => {
  const week = emptyWeek()
  for (const row of schedules) {
    week[row.dayOfWeek]?.push({ start: toHhMm(row.startTime), end: toHhMm(row.endTime) })
  }
  return week.map((ranges) => [...ranges].sort(byStart))
}

/**
 * Punto de partida al pasar a "horario propio": el horario del local. Sin el
 * horario del local cargado, la semana arranca cerrada.
 */
export const draftFromStoreHours = (businessHours: BusinessHours | undefined): WeekDraft =>
  BUSINESS_HOURS_DAY_KEYS.map((key) =>
    (businessHours?.[key] ?? [])
      .map((period) => ({ start: toHhMm(period.open), end: toHhMm(period.close) }))
      .sort(byStart)
  )

const LAST_MINUTE = '23:59'

const plusHours = (hhmm: string, hours: number): string => {
  const [h = 0, m = 0] = hhmm.split(':').map(Number)
  const total = Math.min(h * 60 + m + hours * 60, 23 * 60 + 59)
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

/**
 * Franja que se agrega con "+ Agregar franja": arranca donde termina la
 * ultima del dia (un horario partido tipico) y dura hasta 4 horas.
 */
export const nextRange = (ranges: readonly WeekRange[]): WeekRange => {
  const sorted = ranges.filter(isValidRange).sort(byStart)
  const last = sorted[sorted.length - 1]
  if (!last || last.end >= LAST_MINUTE) return { ...DEFAULT_RANGE }
  return { start: last.end, end: plusHours(last.end, 4) }
}

/** Copia las franjas de `day` a todos los dias de la semana. */
export const copyDayToAll = (draft: WeekDraft, day: number): WeekDraft => {
  const source = draft[day] ?? []
  return draft.map(() => source.map((range) => ({ ...range })))
}

export const replaceDay = (
  draft: WeekDraft,
  day: number,
  ranges: readonly WeekRange[]
): WeekDraft => draft.map((current, index) => (index === day ? ranges : current))

/**
 * `first_overlapping_day` del backend: se pisan si una empieza antes de que
 * termine la anterior; tocarse en el borde (09-13 y 13-17) es valido.
 */
const hasOverlap = (ranges: readonly WeekRange[]): boolean => {
  const sorted = ranges.filter(isValidRange).sort(byStart)
  return sorted.some((range, index) => index > 0 && range.start < (sorted[index - 1]?.end ?? ''))
}

interface WeekValidation {
  /** Un mensaje por dia (indice 0 = lunes), o `null` si el dia esta bien. */
  dayErrors: (string | null)[]
  /** Problema de la semana entera, o `null`. */
  weekError: string | null
  isValid: boolean
}

export const validateWeek = (mode: ScheduleMode, draft: WeekDraft): WeekValidation => {
  if (mode === 'store') {
    return { dayErrors: WEEK_DAYS.map(() => null), weekError: null, isValid: true }
  }
  const dayErrors = WEEK_DAYS.map((_, day) => {
    const ranges = draft[day] ?? []
    if (!ranges.every(isValidRange)) {
      return 'Cada franja necesita inicio y fin, con el inicio antes del fin.'
    }
    if (hasOverlap(ranges)) return 'Las franjas de este día se superponen.'
    return null
  })
  const weekError = draft.some((ranges) => ranges.length > 0)
    ? null
    : 'Marcá al menos un día de trabajo, o elegí "Usa el horario de la tienda".'
  return {
    dayErrors,
    weekError,
    isValid: weekError === null && dayErrors.every((error) => error === null)
  }
}

/** Lo que se guarda: la lista vacia en modo tienda, la semana en modo propio. */
export const weekToSchedules = (mode: ScheduleMode, draft: WeekDraft): StaffSchedule[] =>
  mode === 'store'
    ? []
    : draft.flatMap((ranges, dayOfWeek) =>
        [...ranges].sort(byStart).map((range) => ({
          dayOfWeek,
          startTime: `${range.start}:00`,
          endTime: `${range.end}:00`
        }))
      )

const SAVE_FALLBACK = 'No se pudo guardar el horario. Probá de nuevo.'

/** `detail.day_of_week` del 422 `SCHEDULE_OVERLAP` (`core/exceptions.py`). */
const overlapDayOf = (error: unknown): number | undefined => {
  const detail =
    typeof error === 'object' && error !== null
      ? (error as { context?: { detail?: unknown } }).context?.detail
      : undefined
  const day =
    typeof detail === 'object' && detail !== null
      ? (detail as { day_of_week?: unknown }).day_of_week
      : undefined
  return typeof day === 'number' ? day : undefined
}

/**
 * Texto del error al guardar (regla 20: nada crudo del servidor). Una
 * superposicion nombra el dia; el resto sale de la tabla de codigos.
 */
export const scheduleSaveErrorMessage = (error: unknown): string => {
  if (getErrorCode(error) === 'SCHEDULE_OVERLAP') {
    const day = overlapDayOf(error)
    const label = day === undefined ? undefined : WEEK_DAYS[day]?.label
    if (label) return `El ${label} tiene franjas que se superponen. Corregilas y volvé a guardar.`
  }
  return getErrorMessage(error, SAVE_FALLBACK)
}

/** Resumen corto para la tarjeta del profesional. */
export const summarizeSchedules = (schedules: readonly StaffSchedule[]): string => {
  if (schedules.length === 0) return 'Horario de la tienda'
  const days = new Set(schedules.map((row) => row.dayOfWeek))
  return WEEK_DAYS.filter((_, day) => days.has(day))
    .map((day) => day.short)
    .join(', ')
}
