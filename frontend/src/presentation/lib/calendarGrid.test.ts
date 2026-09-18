import { MIN_APPOINTMENT_MINUTES, SLOT_HEIGHT_PX, gridPlacement } from './calendarGrid'

/**
 * La grilla arranca a las 04:00 y cada franja de 15 minutos mide 64px, asi que
 * una hora de pared son 4 franjas = 256px por encima del origen.
 */
const topPxFor = (hour: number, minute = 0) => ((hour * 60 + minute - 4 * 60) / 15) * SLOT_HEIGHT_PX

describe('gridPlacement', () => {
  it('ubica el turno en la fila de su hora argentina, no la UTC', () => {
    // 09:00 ART = 12:00Z. Con `getUTCHours()` la tarjeta caia en la fila
    // rotulada "12:00", tres horas por debajo de donde decia su propio texto.
    const placement = gridPlacement(
      '2026-09-15T12:00:00Z',
      '2026-09-15T13:00:00Z',
      MIN_APPOINTMENT_MINUTES
    )
    expect(placement.top).toBe(`${topPxFor(9)}px`)
    expect(placement.top).not.toBe(`${topPxFor(12)}px`)
  })

  it('un turno de 21:00 ART cae en su dia, aunque en UTC ya sea el siguiente', () => {
    const placement = gridPlacement('2026-09-16T00:00:00Z', '2026-09-16T01:00:00Z')
    expect(placement.top).toBe(`${topPxFor(21)}px`)
  })

  it('respeta el piso de duracion de un turno corto', () => {
    // 15 minutos reales, pero se dibuja como 30 para que entre el contenido.
    const placement = gridPlacement(
      '2026-09-15T12:00:00Z',
      '2026-09-15T12:15:00Z',
      MIN_APPOINTMENT_MINUTES
    )
    expect(placement.height).toBe(`${(MIN_APPOINTMENT_MINUTES / 15) * SLOT_HEIGHT_PX}px`)
  })

  it('un bloqueo se dibuja con su duracion real, con el minimo de una franja', () => {
    const corto = gridPlacement('2026-09-15T12:00:00Z', '2026-09-15T12:15:00Z')
    expect(corto.height).toBe(`${SLOT_HEIGHT_PX}px`)

    const largo = gridPlacement('2026-09-15T12:00:00Z', '2026-09-15T14:00:00Z')
    expect(largo.height).toBe(`${(120 / 15) * SLOT_HEIGHT_PX}px`)
  })

  it('no empuja hacia arriba lo que empieza antes del inicio de la grilla', () => {
    // 02:00 ART, previo a la primera franja: se apoya en el tope, no en negativo.
    const placement = gridPlacement('2026-09-15T05:00:00Z', '2026-09-15T06:00:00Z')
    expect(placement.top).toBe('0px')
  })

  it('un instante ilegible no emite NaN', () => {
    const placement = gridPlacement('', 'tampoco-es-fecha')
    expect(placement).toEqual({ top: '0px', height: `${SLOT_HEIGHT_PX}px` })
  })

  it('un evento que cruza la medianoche se dibuja con la altura minima', () => {
    // Comportamiento preexistente que este cambio conserva: la grilla es de un
    // solo dia, asi que la duracion da negativa y cae al piso de una franja.
    // Corregirlo es otro trabajo; el test lo deja escrito, no lo tapa.
    const placement = gridPlacement('2026-09-16T02:00:00Z', '2026-09-16T04:00:00Z')
    expect(placement.height).toBe(`${SLOT_HEIGHT_PX}px`)
  })
})
