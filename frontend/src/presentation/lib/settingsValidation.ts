/**
 * Reglas del formulario de Configuracion que el backend ya aplica con un 422.
 * Se repiten aca para avisar ANTES de guardar; la fuente de verdad sigue
 * siendo el backend y cada regla cita de donde sale.
 */

import type { BusinessHoursPeriod, SettingsFormData } from './settingsDraft'

/** `StoreUpdate` en `backend/modules/stores/schemas.py` (MAX_HORAS_ANIO, MAX_MINUTOS_DIA). */
export const SETTINGS_LIMITS = {
  cancellation_hours: { min: 0, max: 8760 },
  buffer_minutes: { min: 0, max: 1440 }
} as const

export const numberInRange = (raw: string, min: number, max: number): number => {
  const parsed = parseInt(raw, 10)
  if (Number.isNaN(parsed)) return min
  return Math.min(max, Math.max(min, parsed))
}

/** `SLUG_PATTERN` en `backend/core/validation.py`. */
const SLUG_PATTERN = /^[a-z0-9][a-z0-9-]{0,98}[a-z0-9]$/

/**
 * Lo que se tipea en el slug, llevado al alfabeto del backend. Los guiones de
 * los extremos NO se recortan: se normaliza en cada tecla, y recortarlos
 * impediria escribir "mi-" camino a "mi-local". Ese caso lo marca la
 * validacion.
 */
export const normalizeSlugInput = (raw: string): string =>
  raw
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/\s+/g, '-')
    .replace(/[^a-z0-9-]/g, '')

/**
 * `BusinessHourPeriod.validate_time_order`: apertura estrictamente antes del
 * cierre. "HH:MM" con ceros a la izquierda se compara bien como texto.
 */
export const isValidPeriod = (period: BusinessHoursPeriod): boolean =>
  period.open !== '' && period.close !== '' && period.open < period.close

export const DAYS = [
  { id: 'mon', label: 'Lunes' },
  { id: 'tue', label: 'Martes' },
  { id: 'wed', label: 'Miércoles' },
  { id: 'thu', label: 'Jueves' },
  { id: 'fri', label: 'Viernes' },
  { id: 'sat', label: 'Sábado' },
  { id: 'sun', label: 'Domingo' }
]

type SettingsDraftErrors = Partial<Record<'slug' | 'business_hours', string>>

/**
 * Solo se valida lo que esta en el borrador: un valor que viene del servidor
 * no lo edito nadie y no tiene por que frenar el guardado.
 */
export const validateSettingsDraft = (draft: Partial<SettingsFormData>): SettingsDraftErrors => {
  const errors: SettingsDraftErrors = {}
  if (draft.slug !== undefined && !SLUG_PATTERN.test(draft.slug)) {
    errors.slug =
      'El enlace lleva de 2 a 100 letras minúsculas, números o guiones, sin guion al principio ni al final.'
  }
  const hours = draft.business_hours
  if (hours === undefined) return errors
  const messages: string[] = []
  // El borrador lleva el objeto ENTERO: tocar un dia reenvia tambien los
  // demas, y un dia legado con varios periodos (la base no tiene unicidad
  // por dia) haria fallar el guardado con un 422 que el admin no ubica.
  for (const day of DAYS) {
    const count = hours[day.id]?.length ?? 0
    if (count > 1) {
      messages.push(
        `El ${day.label} tiene ${count} horarios guardados; por ahora se admite uno. Elegí cuál conservar.`
      )
    }
  }
  if (!Object.values(hours).every((periods) => periods.every(isValidPeriod))) {
    messages.push('Cada día abierto necesita apertura y cierre, con la apertura antes.')
  }
  if (messages.length > 0) errors.business_hours = messages.join(' ')
  return errors
}
