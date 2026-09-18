import {
  GRID_SLOT_LABELS,
  MIN_APPOINTMENT_MINUTES,
  SLOT_HEIGHT_PX,
  gridPlacement
} from './calendarGrid'
import { resetUnreadableInstantReports } from './reportUnreadableInstant'

/**
 * La grilla arranca a las 04:00 y cada franja de 15 minutos mide 64px, asi que
 * una hora de pared son 4 franjas = 256px por encima del origen. Los valores
 * van a mano a proposito: el test afirma el contrato visible, no repite la
 * aritmetica de la implementacion.
 */
const topPxFor = (hour: number, minute = 0) => ((hour * 60 + minute - 4 * 60) / 15) * SLOT_HEIGHT_PX

/** `gridPlacement` devuelve null para lo ilegible; estos casos no lo son. */
const place = (...args: Parameters<typeof gridPlacement>) => {
  const placement = gridPlacement(...args)
  if (!placement) throw new Error('se esperaba una ubicacion, no null')
  return placement
}

beforeEach(() => {
  resetUnreadableInstantReports()
})

describe('gridPlacement', () => {
  it('ubica el turno en la fila de su hora argentina, no la UTC', () => {
    // 09:00 ART = 12:00Z. Con `getUTCHours()` la tarjeta caia en la fila
    // rotulada "12:00", tres horas por debajo de donde decia su propio texto.
    const placement = place('2026-09-15T12:00:00Z', '2026-09-15T13:00:00Z', MIN_APPOINTMENT_MINUTES)
    expect(placement.top).toBe(`${topPxFor(9)}px`)
    expect(placement.top).not.toBe(`${topPxFor(12)}px`)
  })

  it('un turno de 21:00 ART cae en su dia, aunque en UTC ya sea el siguiente', () => {
    const placement = place('2026-09-16T00:00:00Z', '2026-09-16T01:00:00Z')
    expect(placement.top).toBe(`${topPxFor(21)}px`)
  })

  it('respeta el piso de duracion de un turno corto', () => {
    // 15 minutos reales, pero se dibuja como 30 para que entre el contenido.
    const placement = place('2026-09-15T12:00:00Z', '2026-09-15T12:15:00Z', MIN_APPOINTMENT_MINUTES)
    expect(placement.height).toBe(`${(MIN_APPOINTMENT_MINUTES / 15) * SLOT_HEIGHT_PX}px`)
  })

  it('un bloqueo se dibuja con su duracion real, con el minimo de una franja', () => {
    expect(place('2026-09-15T12:00:00Z', '2026-09-15T12:15:00Z').height).toBe(`${SLOT_HEIGHT_PX}px`)
    expect(place('2026-09-15T12:00:00Z', '2026-09-15T14:00:00Z').height).toBe(
      `${(120 / 15) * SLOT_HEIGHT_PX}px`
    )
  })

  it('no empuja hacia arriba lo que empieza antes del inicio de la grilla', () => {
    // 02:00 ART, previo a la primera franja: se apoya en el tope, no en negativo.
    expect(place('2026-09-15T05:00:00Z', '2026-09-15T06:00:00Z').top).toBe('0px')
  })

  it('devuelve null ante un instante ilegible, para que no se dibuje', () => {
    // Ubicarlo en top 0 lo apilaba sobre un turno legitimo previo a las 04:00.
    expect(gridPlacement('', 'tampoco-es-fecha')).toBeNull()
    expect(gridPlacement('2026-09-15T12:00:00Z', 'no-es-fecha')).toBeNull()
  })

  it('un evento que cruza la medianoche se dibuja con la altura minima', () => {
    // Comportamiento preexistente que este cambio conserva: la grilla es de un
    // solo dia, asi que la duracion da negativa y cae al piso de una franja.
    // Corregirlo es otro trabajo; el test lo deja escrito, no lo tapa.
    expect(place('2026-09-16T02:00:00Z', '2026-09-16T04:00:00Z').height).toBe(`${SLOT_HEIGHT_PX}px`)
  })
})

describe('GRID_SLOT_LABELS', () => {
  it('rotula desde las 04:00 de a 15 minutos', () => {
    expect(GRID_SLOT_LABELS[0]).toBe('04:00')
    expect(GRID_SLOT_LABELS[1]).toBe('04:15')
    expect(GRID_SLOT_LABELS[4]).toBe('05:00')
  })

  it('cubre 12 horas: la grilla termina a las 15:45 y lo posterior no se dibuja', () => {
    expect(GRID_SLOT_LABELS).toHaveLength(48)
    expect(GRID_SLOT_LABELS.at(-1)).toBe('15:45')
  })

  it('cada rotulo tiene una franja, y la ubicacion usa el mismo alto', () => {
    // El acoplamiento que antes vivia entre `h-16` y un 64 hardcodeado.
    expect(place('2026-09-15T07:00:00Z', '2026-09-15T08:00:00Z').top).toBe(
      `${GRID_SLOT_LABELS.indexOf('04:00') * SLOT_HEIGHT_PX}px`
    )
  })
})
