/**
 * Geometria de la grilla de la vista dia del calendario.
 *
 * Hasta 2026-09-18 la grilla era fija: 48 franjas de 15 minutos desde las
 * 04:00, o sea que terminaba a las 15:45. Una tienda con jornada partida
 * (en Tucuman, manana y tarde con siesta en el medio) no tenia donde dibujar
 * el turno tarde, y las horas de siesta ocupaban grilla muerta que igual
 * habia que scrollear.
 *
 * Ahora la grilla se arma con los horarios reales de la tienda. Dos reglas la
 * sostienen:
 *
 * 1. El rango visible es la union de los horarios de atencion Y los eventos
 *    del dia. Un turno fuera de horario (movido a mano, heredado, cargado por
 *    el dueno) estira la grilla en vez de caerse: acotar la ventana sin esta
 *    union es justamente como se perdian los turnos de la tarde.
 * 2. Los huecos entre tramos abiertos se colapsan en una banda fina. No se
 *    borran: el hueco se sigue viendo, con su rango, y se puede expandir.
 */

import { argentinaMinutesOfDay } from '@shared/utils/argentinaTime'

import { reportUnreadableInstant } from './reportUnreadableInstant'

export const SLOT_MINUTES = 15
/** Alto de cada franja, en px. La fila y la tarjeta salen de este mismo valor. */
export const SLOT_HEIGHT_PX = 64
/** Alto de un hueco colapsado: una banda, no una franja por hora cerrada. */
export const COLLAPSED_GAP_HEIGHT_PX = 44

/**
 * Piso de duracion visual de un turno: uno de 15 minutos quedaria demasiado
 * chico para leer el nombre del cliente y las acciones.
 */
export const MIN_APPOINTMENT_MINUTES = 30

/**
 * Un hueco mas corto que esto no se colapsa: la banda ocuparia casi lo mismo
 * que las franjas que reemplaza, y cortar la grilla cada media hora se lee
 * peor que dejar el vacio.
 */
const MIN_COLLAPSIBLE_GAP_MINUTES = 60

/** Sin horarios ni eventos igual hay que poder mirar y cargar el dia. */
const FALLBACK_OPEN_RANGE: TimeRange = { startMinutes: 8 * 60, endMinutes: 20 * 60 }

const MINUTES_IN_DAY = 24 * 60

interface TimeRange {
  startMinutes: number
  endMinutes: number
}

interface SlotLabel {
  text: string
  topPx: number
}

interface BandBase {
  startMinutes: number
  endMinutes: number
  topPx: number
  heightPx: number
}

export interface OpenBand extends BandBase {
  kind: 'open'
  labels: SlotLabel[]
}

export interface ClosedBand extends BandBase {
  kind: 'closed'
  /** Identidad estable del hueco, para recordar cual esta expandido. */
  key: string
  label: string
  expanded: boolean
}

type GridBand = OpenBand | ClosedBand

interface DayGrid {
  bands: GridBand[]
  totalHeightPx: number
}

interface GridPlacement {
  top: string
  height: string
}

const pad = (value: number): string => String(value).padStart(2, '0')

const minutesToLabel = (minutes: number): string =>
  `${pad(Math.floor(minutes / 60) % 24)}:${pad(minutes % 60)}`

/** `HH:mm` -> minutos desde medianoche. `null` si no se puede leer. */
export const parseHhMm = (value: string): number | null => {
  const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim())
  if (!match) return null
  const hours = Number(match[1])
  const minutes = Number(match[2])
  if (hours > 23 || minutes > 59) return null
  return hours * 60 + minutes
}

const floorToSlot = (minutes: number) => Math.floor(minutes / SLOT_MINUTES) * SLOT_MINUTES
const ceilToSlot = (minutes: number) => Math.ceil(minutes / SLOT_MINUTES) * SLOT_MINUTES

/**
 * Ordena y funde los tramos que se tocan o se superponen. Es lo que hace que
 * un turno dentro de la siesta parta el hueco solo, sin ningun caso especial:
 * entra como un tramo abierto mas y la fusion resuelve el resto.
 */
export const mergeRanges = (ranges: readonly TimeRange[]): TimeRange[] => {
  const usable = ranges
    .filter((range) => range.endMinutes > range.startMinutes)
    .map((range) => ({
      startMinutes: Math.max(0, floorToSlot(range.startMinutes)),
      endMinutes: Math.min(MINUTES_IN_DAY, ceilToSlot(range.endMinutes))
    }))
    .sort((left, right) => left.startMinutes - right.startMinutes)

  const merged: TimeRange[] = []
  for (const range of usable) {
    const last = merged[merged.length - 1]
    if (last && range.startMinutes <= last.endMinutes) {
      last.endMinutes = Math.max(last.endMinutes, range.endMinutes)
      continue
    }
    merged.push({ ...range })
  }
  return merged
}

const buildLabels = (range: TimeRange, topPx: number): SlotLabel[] => {
  const labels: SlotLabel[] = []
  for (
    let minutes = range.startMinutes, index = 0;
    minutes < range.endMinutes;
    minutes += SLOT_MINUTES, index += 1
  ) {
    labels.push({ text: minutesToLabel(minutes), topPx: topPx + index * SLOT_HEIGHT_PX })
  }
  return labels
}

/**
 * Arma la grilla del dia.
 *
 * `openRanges` ya tiene que traer los horarios de atencion Y los eventos: este
 * modulo no sabe de donde sale cada tramo, solo garantiza que todo lo que
 * entra queda dibujable.
 */
export const buildDayGrid = (
  openRanges: readonly TimeRange[],
  expandedGapKeys: ReadonlySet<string> = new Set()
): DayGrid => {
  const merged = mergeRanges(openRanges)
  const effective = merged.length > 0 ? merged : mergeRanges([FALLBACK_OPEN_RANGE])

  const bands: GridBand[] = []
  let topPx = 0

  effective.forEach((range, index) => {
    const previous = effective[index - 1]
    if (previous) {
      const gap: TimeRange = {
        startMinutes: previous.endMinutes,
        endMinutes: range.startMinutes
      }
      const gapMinutes = gap.endMinutes - gap.startMinutes
      const key = `${gap.startMinutes}-${gap.endMinutes}`
      const collapsible = gapMinutes >= MIN_COLLAPSIBLE_GAP_MINUTES
      const expanded = !collapsible || expandedGapKeys.has(key)
      const heightPx = expanded
        ? (gapMinutes / SLOT_MINUTES) * SLOT_HEIGHT_PX
        : COLLAPSED_GAP_HEIGHT_PX
      bands.push({
        kind: 'closed',
        key,
        startMinutes: gap.startMinutes,
        endMinutes: gap.endMinutes,
        label: `${minutesToLabel(gap.startMinutes)} - ${minutesToLabel(gap.endMinutes)}`,
        expanded,
        topPx,
        heightPx
      })
      topPx += heightPx
    }

    const heightPx = ((range.endMinutes - range.startMinutes) / SLOT_MINUTES) * SLOT_HEIGHT_PX
    bands.push({
      kind: 'open',
      startMinutes: range.startMinutes,
      endMinutes: range.endMinutes,
      topPx,
      heightPx,
      labels: buildLabels(range, topPx)
    })
    topPx += heightPx
  })

  return { bands, totalHeightPx: topPx }
}

/**
 * Pixel vertical de un minuto de pared. `null` si cae en un hueco que no se
 * dibuja a escala; el llamador construye la grilla incluyendo los eventos, asi
 * que en la practica eso no pasa con un turno real.
 */
export const minuteToTopPx = (grid: DayGrid, minutes: number): number | null => {
  for (const band of grid.bands) {
    if (minutes < band.startMinutes || minutes >= band.endMinutes) continue
    if (band.kind === 'open') {
      return band.topPx + ((minutes - band.startMinutes) / SLOT_MINUTES) * SLOT_HEIGHT_PX
    }
    if (!band.expanded) return band.topPx
    return band.topPx + ((minutes - band.startMinutes) / SLOT_MINUTES) * SLOT_HEIGHT_PX
  }
  return null
}

/**
 * Ubica un evento en la grilla a partir de sus instantes ISO.
 *
 * `minDurationMinutes` es el piso de duracion visual: los turnos pasan
 * `MIN_APPOINTMENT_MINUTES`, los bloqueos se dibujan con su duracion real.
 *
 * Devuelve `null` cuando algun instante es ilegible, y el llamador no lo
 * dibuja. Ubicarlo al tope lo apilaba sobre un turno legitimo, en columnas
 * `position: absolute` sin orden garantizado: una tarjeta con datos rotos
 * tapando una real es peor que una ausente, sobre todo porque la ausencia
 * queda registrada en la telemetria.
 */
export const gridPlacement = (
  grid: DayGrid,
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

  const topPx = minuteToTopPx(grid, startMinutes)
  if (topPx === null) return null

  const durationMinutes = Math.max(endMinutes - startMinutes, minDurationMinutes)
  const heightPx = Math.max((durationMinutes / SLOT_MINUTES) * SLOT_HEIGHT_PX, SLOT_HEIGHT_PX)
  return { top: `${topPx}px`, height: `${heightPx}px` }
}

/** Minutos de pared de un instante ISO, como rango dibujable del dia. */
export const rangeFromInstants = (startIso: string, endIso: string): TimeRange | null => {
  const startMinutes = argentinaMinutesOfDay(startIso)
  const endMinutes = argentinaMinutesOfDay(endIso)
  if (startMinutes === null || endMinutes === null) return null
  // Un evento que cruza la medianoche se recorta al final del dia: la grilla
  // es de un solo dia y el resto pertenece al siguiente.
  return { startMinutes, endMinutes: Math.max(endMinutes, startMinutes + SLOT_MINUTES) }
}
