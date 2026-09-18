import {
  COLLAPSED_GAP_HEIGHT_PX,
  MIN_APPOINTMENT_MINUTES,
  SLOT_HEIGHT_PX,
  SLOT_MINUTES,
  type ClosedBand,
  type OpenBand,
  buildDayGrid,
  gridPlacement,
  mergeRanges,
  minuteToTopPx,
  parseHhMm,
  rangeFromInstants
} from './calendarGrid'
import { resetUnreadableInstantReports } from './reportUnreadableInstant'

const hhmm = (hour: number, minute = 0) => hour * 60 + minute
const range = (from: number, to: number) => ({ startMinutes: hhmm(from), endMinutes: hhmm(to) })

/** Jornada partida tipica de Tucuman: manana, siesta, tarde. */
const TUCUMAN = [range(9, 13), range(17, 21)]

const openBands = (grid: ReturnType<typeof buildDayGrid>) =>
  grid.bands.filter((band): band is OpenBand => band.kind === 'open')
const closedBands = (grid: ReturnType<typeof buildDayGrid>) =>
  grid.bands.filter((band): band is ClosedBand => band.kind === 'closed')

beforeEach(() => {
  resetUnreadableInstantReports()
})

describe('parseHhMm', () => {
  it('lee las horas de atencion tal como las guarda la tienda', () => {
    expect(parseHhMm('09:00')).toBe(540)
    expect(parseHhMm('9:30')).toBe(570)
  })

  it('devuelve null ante algo que no es una hora', () => {
    expect(parseHhMm('')).toBeNull()
    expect(parseHhMm('25:00')).toBeNull()
    expect(parseHhMm('09:70')).toBeNull()
    expect(parseHhMm('manana')).toBeNull()
  })
})

describe('mergeRanges', () => {
  it('funde tramos que se tocan o se superponen', () => {
    expect(mergeRanges([range(9, 13), range(12, 14)])).toEqual([range(9, 14)])
    expect(mergeRanges([range(9, 13), range(13, 15)])).toEqual([range(9, 15)])
  })

  it('conserva separados los tramos de una jornada partida', () => {
    expect(mergeRanges(TUCUMAN)).toEqual(TUCUMAN)
  })

  it('ordena y descarta lo vacio o invertido', () => {
    expect(mergeRanges([range(17, 21), range(9, 13), range(11, 11)])).toEqual(TUCUMAN)
  })

  it('alinea a la franja hacia afuera, para no cortar media fila', () => {
    const [merged] = mergeRanges([{ startMinutes: 9 * 60 + 7, endMinutes: 13 * 60 + 8 }])
    expect(merged).toEqual({ startMinutes: 9 * 60, endMinutes: 13 * 60 + 15 })
  })
})

describe('buildDayGrid — jornada partida', () => {
  it('colapsa la siesta en una banda en vez de cuatro horas de vacio', () => {
    const grid = buildDayGrid(TUCUMAN)
    const [siesta] = closedBands(grid)

    expect(siesta?.label).toBe('13:00 - 17:00')
    expect(siesta?.heightPx).toBe(COLLAPSED_GAP_HEIGHT_PX)
    // A escala esas 4 horas ocuparian 16 franjas.
    expect(siesta?.heightPx).toBeLessThan(16 * SLOT_HEIGHT_PX)
  })

  it('el dia entero entra en mucho menos alto que la grilla fija anterior', () => {
    const grid = buildDayGrid(TUCUMAN)
    // Antes: 48 franjas fijas, sin importar el horario de la tienda.
    expect(grid.totalHeightPx).toBeLessThan(48 * SLOT_HEIGHT_PX)
    // 8 horas abiertas = 32 franjas, mas la banda del hueco.
    expect(grid.totalHeightPx).toBe(32 * SLOT_HEIGHT_PX + COLLAPSED_GAP_HEIGHT_PX)
  })

  it('rotula cada tramo con su propia hora', () => {
    const [manana, tarde] = openBands(buildDayGrid(TUCUMAN))
    expect(manana?.labels[0]?.text).toBe('09:00')
    expect(manana?.labels.at(-1)?.text).toBe('12:45')
    expect(tarde?.labels[0]?.text).toBe('17:00')
    expect(tarde?.labels.at(-1)?.text).toBe('20:45')
  })

  it('expandir la siesta la devuelve a escala real', () => {
    const grid = buildDayGrid(TUCUMAN, new Set(['780-1020']))
    const [siesta] = closedBands(grid)
    expect(siesta?.expanded).toBe(true)
    expect(siesta?.heightPx).toBe(16 * SLOT_HEIGHT_PX)
  })

  it('un hueco de media hora se deja a escala: la banda ocuparia casi lo mismo', () => {
    const grid = buildDayGrid([range(9, 13), { startMinutes: hhmm(13, 30), endMinutes: hhmm(18) }])
    const [corto] = closedBands(grid)
    expect(corto?.expanded).toBe(true)
    expect(corto?.heightPx).toBe(2 * SLOT_HEIGHT_PX)
  })
})

describe('buildDayGrid — nada se cae de la grilla', () => {
  it('un turno fuera del horario de atencion estira la grilla', () => {
    // 21:30, despues de cerrar: antes caia fuera de la grilla rotulada.
    const grid = buildDayGrid([...TUCUMAN, range(21, 22)])
    const tarde = openBands(grid).at(-1)
    expect(tarde?.endMinutes).toBe(hhmm(22))
    expect(minuteToTopPx(grid, hhmm(21, 30))).not.toBeNull()
  })

  it('un turno dentro de la siesta parte el hueco en dos', () => {
    const grid = buildDayGrid([...TUCUMAN, range(15, 16)])
    const huecos = closedBands(grid)
    expect(huecos.map((band) => band.label)).toEqual(['13:00 - 15:00', '16:00 - 17:00'])
    expect(minuteToTopPx(grid, hhmm(15, 30))).not.toBeNull()
  })

  it('sin horarios ni eventos igual se puede mirar y cargar el dia', () => {
    const grid = buildDayGrid([])
    expect(openBands(grid)).toHaveLength(1)
    expect(grid.totalHeightPx).toBeGreaterThan(0)
  })
})

describe('minuteToTopPx', () => {
  it('el minuto de apertura esta en el tope', () => {
    expect(minuteToTopPx(buildDayGrid(TUCUMAN), hhmm(9))).toBe(0)
  })

  it('una hora son cuatro franjas', () => {
    expect(minuteToTopPx(buildDayGrid(TUCUMAN), hhmm(10))).toBe(4 * SLOT_HEIGHT_PX)
  })

  it('el tramo tarde arranca despues del hueco colapsado, no a escala', () => {
    const grid = buildDayGrid(TUCUMAN)
    // 4 horas de manana = 16 franjas, mas la banda del hueco.
    expect(minuteToTopPx(grid, hhmm(17))).toBe(16 * SLOT_HEIGHT_PX + COLLAPSED_GAP_HEIGHT_PX)
  })

  it('un minuto fuera de todo tramo no tiene lugar', () => {
    expect(minuteToTopPx(buildDayGrid(TUCUMAN), hhmm(6))).toBeNull()
  })
})

describe('gridPlacement', () => {
  const grid = buildDayGrid(TUCUMAN)

  it('ubica el turno por su hora argentina, no la UTC', () => {
    // 09:00 ART = 12:00Z. Con getUTCHours() la tarjeta caia tres horas abajo.
    const placement = gridPlacement(
      grid,
      '2026-09-15T12:00:00Z',
      '2026-09-15T13:00:00Z',
      MIN_APPOINTMENT_MINUTES
    )
    expect(placement?.top).toBe('0px')
  })

  it('un turno de la tarde se dibuja, que es lo que antes no pasaba', () => {
    // 18:00 ART = 21:00Z. La grilla vieja terminaba a las 15:45.
    const placement = gridPlacement(grid, '2026-09-15T21:00:00Z', '2026-09-15T22:00:00Z')
    expect(placement).not.toBeNull()
    expect(placement?.top).toBe(`${20 * SLOT_HEIGHT_PX + COLLAPSED_GAP_HEIGHT_PX}px`)
  })

  it('respeta el piso de duracion de un turno corto', () => {
    const placement = gridPlacement(
      grid,
      '2026-09-15T12:00:00Z',
      '2026-09-15T12:15:00Z',
      MIN_APPOINTMENT_MINUTES
    )
    expect(placement?.height).toBe(`${(MIN_APPOINTMENT_MINUTES / SLOT_MINUTES) * SLOT_HEIGHT_PX}px`)
  })

  it('un bloqueo se dibuja con su duracion real, con el minimo de una franja', () => {
    expect(gridPlacement(grid, '2026-09-15T12:00:00Z', '2026-09-15T12:15:00Z')?.height).toBe(
      `${SLOT_HEIGHT_PX}px`
    )
    expect(gridPlacement(grid, '2026-09-15T12:00:00Z', '2026-09-15T14:00:00Z')?.height).toBe(
      `${(120 / SLOT_MINUTES) * SLOT_HEIGHT_PX}px`
    )
  })

  it('devuelve null ante un instante ilegible, para que no se dibuje', () => {
    expect(gridPlacement(grid, '', 'tampoco-es-fecha')).toBeNull()
    expect(gridPlacement(grid, '2026-09-15T12:00:00Z', 'no-es-fecha')).toBeNull()
  })
})

describe('rangeFromInstants', () => {
  it('convierte un turno en el tramo que tiene que quedar abierto', () => {
    expect(rangeFromInstants('2026-09-15T12:00:00Z', '2026-09-15T13:00:00Z')).toEqual({
      startMinutes: hhmm(9),
      endMinutes: hhmm(10)
    })
  })

  it('un evento que cruza la medianoche se recorta, no da negativo', () => {
    // 23:00 -> 01:00 del dia siguiente: la grilla es de un solo dia.
    const recortado = rangeFromInstants('2026-09-16T02:00:00Z', '2026-09-16T04:00:00Z')
    expect(recortado?.endMinutes).toBeGreaterThan(recortado?.startMinutes ?? 0)
  })

  it('devuelve null ante un instante ilegible', () => {
    expect(rangeFromInstants('no', 'tampoco')).toBeNull()
  })
})
