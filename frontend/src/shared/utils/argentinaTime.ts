/**
 * Hora argentina para todo lo que ve el cliente.
 *
 * La API persiste y devuelve instantes en UTC (`starts_at`, `ends_at` en ISO).
 * Shifty opera solo en Argentina, asi que mostrar o tipear una hora es siempre
 * en America/Argentina/Buenos_Aires, independientemente de la zona del
 * navegador. Antes el flujo publico mostraba la hora UTC del slot ("12:00"
 * para un turno de 09:00) y al reservar recomponia fecha local + hora UTC,
 * con lo que un turno de 21:00 en adelante caia en el dia anterior
 * (2026-09-10).
 */

export const ARGENTINA_TZ = 'America/Argentina/Buenos_Aires'

const partsFormatter = new Intl.DateTimeFormat('en-US', {
  timeZone: ARGENTINA_TZ,
  hourCycle: 'h23',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit'
})

interface WallClock {
  year: number
  month: number
  day: number
  hour: number
  minute: number
}

const wallClockInArgentina = (instant: Date): WallClock => {
  const parts = partsFormatter.formatToParts(instant)
  const read = (type: Intl.DateTimeFormatPartTypes): number =>
    Number(parts.find((part) => part.type === type)?.value ?? '0')
  return {
    year: read('year'),
    month: read('month'),
    day: read('day'),
    hour: read('hour') % 24,
    minute: read('minute')
  }
}

const pad = (value: number): string => String(value).padStart(2, '0')

const parseInstant = (iso: string): Date | null => {
  const instant = new Date(iso)
  return Number.isNaN(instant.getTime()) ? null : instant
}

/** `HH:mm` en hora argentina de un instante ISO. Cadena vacia si es invalido. */
export const formatArgentinaTime = (iso: string): string => {
  const instant = parseInstant(iso)
  if (!instant) return ''
  const wall = wallClockInArgentina(instant)
  return `${pad(wall.hour)}:${pad(wall.minute)}`
}

/** `yyyy-MM-dd` en hora argentina de un instante ISO. Cadena vacia si es invalido. */
export const formatArgentinaDate = (iso: string): string => {
  const instant = parseInstant(iso)
  if (!instant) return ''
  const wall = wallClockInArgentina(instant)
  return `${wall.year}-${pad(wall.month)}-${pad(wall.day)}`
}

/** `dd/MM/yyyy` en hora argentina, para mostrar a personas. */
export const formatArgentinaDateDisplay = (iso: string): string => {
  const instant = parseInstant(iso)
  if (!instant) return ''
  const wall = wallClockInArgentina(instant)
  return `${pad(wall.day)}/${pad(wall.month)}/${wall.year}`
}

/**
 * Convierte una fecha `yyyy-MM-dd` y una hora `HH:mm` tipeadas en hora
 * argentina al instante UTC en ISO (con `Z`). Es la inversa de
 * `formatArgentinaDate`/`formatArgentinaTime` y no depende de la zona del
 * navegador: calcula el desfase real de la zona en ese instante (hoy -03:00,
 * pero el codigo no lo asume).
 */
export const argentinaLocalToUtcIso = (date: string, time: string): string => {
  const dateParts = date.split('-').map(Number)
  const timeParts = time.split(':').map(Number)
  const year = dateParts[0] ?? NaN
  const month = dateParts[1] ?? NaN
  const day = dateParts[2] ?? NaN
  const hour = timeParts[0] ?? NaN
  const minute = timeParts[1] ?? NaN
  if (
    dateParts.length !== 3 ||
    timeParts.length < 2 ||
    [year, month, day, hour, minute].some((n) => !Number.isFinite(n))
  ) {
    throw new Error(`Fecha u hora invalida: ${date} ${time}`)
  }
  // Se toma la hora tipeada "como si" fuera UTC y se corrige por el desfase
  // que la zona tiene en ese instante.
  const naiveAsUtc = Date.UTC(year, month - 1, day, hour, minute, 0, 0)
  const wall = wallClockInArgentina(new Date(naiveAsUtc))
  const wallAsUtc = Date.UTC(wall.year, wall.month - 1, wall.day, wall.hour, wall.minute, 0, 0)
  const offsetMs = wallAsUtc - naiveAsUtc
  return new Date(naiveAsUtc - offsetMs).toISOString()
}
