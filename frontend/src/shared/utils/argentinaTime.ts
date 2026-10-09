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

const ARGENTINA_TZ = 'America/Argentina/Buenos_Aires'

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

/**
 * `yyyy-MM-dd` sin hora: es una fecha de calendario, no un instante. Pasarla
 * por la conversion de zona la corre un dia hacia atras (medianoche UTC son
 * las 21:00 del dia anterior en Argentina).
 */
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/
const calendarParts = (value: string): WallClock | null => {
  if (!DATE_ONLY.test(value)) return null
  const [year, month, day] = value.split('-').map(Number)
  if (!year || !month || !day) return null
  return { year, month, day, hour: 0, minute: 0 }
}

/** `HH:mm` en hora argentina de un instante ISO. Cadena vacia si es invalido. */
export const formatArgentinaTime = (iso: string): string => {
  const soloFecha = calendarParts(iso)
  if (soloFecha) return `${pad(soloFecha.hour)}:${pad(soloFecha.minute)}`
  const instant = parseInstant(iso)
  if (!instant) return ''
  const wall = wallClockInArgentina(instant)
  return `${pad(wall.hour)}:${pad(wall.minute)}`
}

/** `yyyy-MM-dd` en hora argentina de un instante ISO. Cadena vacia si es invalido. */
export const formatArgentinaDate = (iso: string): string => {
  const soloFecha = calendarParts(iso)
  if (soloFecha) return `${soloFecha.year}-${pad(soloFecha.month)}-${pad(soloFecha.day)}`
  const instant = parseInstant(iso)
  if (!instant) return ''
  const wall = wallClockInArgentina(instant)
  return `${wall.year}-${pad(wall.month)}-${pad(wall.day)}`
}

/** `dd/MM/yyyy` en hora argentina, para mostrar a personas. */
export const formatArgentinaDateDisplay = (iso: string): string => {
  const soloFecha = calendarParts(iso)
  if (soloFecha) return `${pad(soloFecha.day)}/${pad(soloFecha.month)}/${soloFecha.year}`
  const instant = parseInstant(iso)
  if (!instant) return ''
  const wall = wallClockInArgentina(instant)
  return `${pad(wall.day)}/${pad(wall.month)}/${wall.year}`
}

/** Dia de calendario argentino de un `yyyy-MM-dd` o de un instante ISO. */
const argentinaDayOf = (value: string): WallClock | null => {
  const soloFecha = calendarParts(value)
  if (soloFecha) return soloFecha
  const instant = parseInstant(value)
  return instant ? wallClockInArgentina(instant) : null
}

// Nombres de dias y meses en castellano. La fecha ya viene resuelta a dia
// argentino, asi que se formatea como medianoche UTC de ese dia: con la zona
// del navegador un dia podia correrse. Antes la agenda usaba date-fns sin
// locale y mostraba "02 DE OCTOBER" y "MON" (QA 2026-10-02).
const weekdayShortFormatter = new Intl.DateTimeFormat('es-AR', {
  weekday: 'short',
  timeZone: 'UTC'
})
const weekdayLongFormatter = new Intl.DateTimeFormat('es-AR', { weekday: 'long', timeZone: 'UTC' })
const monthLongFormatter = new Intl.DateTimeFormat('es-AR', { month: 'long', timeZone: 'UTC' })
const asUtcDay = (wall: WallClock): Date => new Date(Date.UTC(wall.year, wall.month - 1, wall.day))

/** Dia de la semana abreviado en castellano ("vie"). Cadena vacia si es invalido. */
export const formatArgentinaWeekdayShort = (value: string): string => {
  const wall = argentinaDayOf(value)
  return wall ? weekdayShortFormatter.format(asUtcDay(wall)).replace('.', '') : ''
}

/** "02 de octubre". Cadena vacia si es invalido. */
export const formatArgentinaLongDate = (value: string): string => {
  const wall = argentinaDayOf(value)
  return wall ? `${pad(wall.day)} de ${monthLongFormatter.format(asUtcDay(wall))}` : ''
}

/** Encabezado de un dia en una lista: "viernes 02/10". Cadena vacia si es invalido. */
export const formatArgentinaDayHeading = (value: string): string => {
  const wall = argentinaDayOf(value)
  if (!wall) return ''
  return `${weekdayLongFormatter.format(asUtcDay(wall))} ${pad(wall.day)}/${pad(wall.month)}`
}

/**
 * `dd/MM` en hora argentina, para listas ya acotadas a un rango conocido.
 * Se compone desde el wall clock en vez de recortar la salida de
 * `formatArgentinaDateDisplay`: un slice deja el resultado atado al largo
 * exacto de otro formateador, sin que nada lo sostenga.
 */
export const formatArgentinaDayMonth = (iso: string): string => {
  const soloFecha = calendarParts(iso)
  if (soloFecha) return `${pad(soloFecha.day)}/${pad(soloFecha.month)}`
  const instant = parseInstant(iso)
  if (!instant) return ''
  const wall = wallClockInArgentina(instant)
  return `${pad(wall.day)}/${pad(wall.month)}`
}

/**
 * Minutos transcurridos desde la medianoche argentina de un instante ISO.
 * `null` si el ISO no se puede leer. Es lo que necesita la grilla del
 * calendario para ubicar una tarjeta: la posicion vertical se calcula sobre
 * la hora de pared argentina, igual que el rotulo que la acompania.
 */
export const argentinaMinutesOfDay = (iso: string): number | null => {
  const soloFecha = calendarParts(iso)
  if (soloFecha) return soloFecha.hour * 60 + soloFecha.minute
  const instant = parseInstant(iso)
  if (!instant) return null
  const wall = wallClockInArgentina(instant)
  return wall.hour * 60 + wall.minute
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
    throw new Error(`Fecha u hora inválida: ${date} ${time}`)
  }
  // Se toma la hora tipeada "como si" fuera UTC y se corrige por el desfase
  // que la zona tiene en ese instante.
  const naiveAsUtc = Date.UTC(year, month - 1, day, hour, minute, 0, 0)
  const wall = wallClockInArgentina(new Date(naiveAsUtc))
  const wallAsUtc = Date.UTC(wall.year, wall.month - 1, wall.day, wall.hour, wall.minute, 0, 0)
  const offsetMs = wallAsUtc - naiveAsUtc
  return new Date(naiveAsUtc - offsetMs).toISOString()
}

/**
 * Instante UTC -> valor de un input `datetime-local`, en hora ARGENTINA.
 * Antes usaba la hora del navegador y el valor volvia al backend como naive,
 * que lo interpretaba como UTC: tres horas de deriva en cada guardado.
 * Vivia en `pages/superadmin/shared.ts` (cupones de plataforma); se movio aca
 * cuando aparecio el mismo bug en las promociones de tienda (2026-09-20), que
 * mandaban el `datetime-local` crudo y vencian tres horas antes.
 */
export const toDateTimeInput = (value: string | null | undefined): string => {
  if (!value) return ''
  const fecha = formatArgentinaDate(value)
  const hora = formatArgentinaTime(value)
  return fecha && hora ? `${fecha}T${hora}` : ''
}

/** Valor de un input `datetime-local` (hora argentina) -> instante UTC ISO. */
export const fromDateTimeInput = (value: string): string | null => {
  if (!value) return null
  const [fecha, hora] = value.split('T')
  if (!fecha || !hora) return null
  return argentinaLocalToUtcIso(fecha, hora.slice(0, 5))
}
