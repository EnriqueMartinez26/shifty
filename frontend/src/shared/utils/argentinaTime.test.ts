import { argentinaLocalToUtcIso, formatArgentinaDate, formatArgentinaTime } from './argentinaTime'

describe('argentinaTime', () => {
  it('muestra la hora argentina de un instante UTC (09:00 ART = 12:00Z)', () => {
    expect(formatArgentinaTime('2026-09-15T12:00:00+00:00')).toBe('09:00')
    expect(formatArgentinaTime('2026-09-15T12:00:00Z')).toBe('09:00')
  })

  it('un slot de 00:00Z es 21:00 del dia anterior en Argentina', () => {
    expect(formatArgentinaTime('2026-09-16T00:00:00+00:00')).toBe('21:00')
    expect(formatArgentinaDate('2026-09-16T00:00:00+00:00')).toBe('2026-09-15')
  })

  it('devuelve vacio ante un ISO invalido en vez de romper el render', () => {
    expect(formatArgentinaTime('no-es-una-fecha')).toBe('')
    expect(formatArgentinaDate('')).toBe('')
  })

  it('convierte fecha y hora tipeadas en Argentina al instante UTC', () => {
    expect(argentinaLocalToUtcIso('2026-09-15', '09:00')).toBe('2026-09-15T12:00:00.000Z')
    // 22:00 local cae en el dia UTC siguiente.
    expect(argentinaLocalToUtcIso('2026-09-15', '22:00')).toBe('2026-09-16T01:00:00.000Z')
  })

  it('formatear y convertir son inversas', () => {
    const iso = argentinaLocalToUtcIso('2026-12-31', '23:30')
    expect(formatArgentinaDate(iso)).toBe('2026-12-31')
    expect(formatArgentinaTime(iso)).toBe('23:30')
  })

  it('rechaza entradas malformadas', () => {
    expect(() => argentinaLocalToUtcIso('2026-13', '09:00')).toThrow()
    expect(() => argentinaLocalToUtcIso('2026-09-15', 'nueve')).toThrow()
  })
})
