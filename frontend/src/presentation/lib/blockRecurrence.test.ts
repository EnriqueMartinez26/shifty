import { MAX_BLOCK_OCCURRENCES, addCalendarDays, countOccurrences } from './blockRecurrence'

describe('countOccurrences (FF-13, D-20260929-10)', () => {
  it('sin recurrencia es un solo bloqueo', () => {
    expect(countOccurrences('2026-09-20', '2026-12-31', 'none')).toBe(1)
  })

  it('diaria cuenta los dos extremos', () => {
    expect(countOccurrences('2026-09-20', '2026-09-27', 'daily')).toBe(8)
  })

  it('semanal cuenta cada 7 dias hasta la fecha de fin incluida', () => {
    expect(countOccurrences('2026-09-20', '2026-10-04', 'weekly')).toBe(3)
    expect(countOccurrences('2026-09-20', '2026-10-10', 'weekly')).toBe(3)
    expect(countOccurrences('2026-09-20', '2026-10-11', 'weekly')).toBe(4)
  })

  it('la fecha de fin igual al inicio es un bloqueo; anterior, ninguno', () => {
    expect(countOccurrences('2026-09-20', '2026-09-20', 'daily')).toBe(1)
    expect(countOccurrences('2026-09-20', '2026-09-19', 'daily')).toBe(0)
  })

  it('cruza fin de mes y de anio con aritmetica de calendario', () => {
    expect(countOccurrences('2026-12-30', '2027-01-02', 'daily')).toBe(4)
  })

  it('no recorta en el tope: devuelve N aunque pase de 120 (lo decide quien llama)', () => {
    expect(MAX_BLOCK_OCCURRENCES).toBe(120)
    expect(countOccurrences('2026-01-01', '2026-04-30', 'daily')).toBe(120)
    expect(countOccurrences('2026-01-01', '2026-05-01', 'daily')).toBe(121)
  })

  it('una fecha ilegible no cuenta ningun bloqueo', () => {
    expect(countOccurrences('2026-09-20', '', 'daily')).toBe(0)
    expect(countOccurrences('', '2026-09-20', 'weekly')).toBe(0)
  })

  it('addCalendarDays corre la fecha por calendario', () => {
    expect(addCalendarDays('2026-12-28', 7)).toBe('2027-01-04')
    expect(addCalendarDays('', 7)).toBe('')
  })
})
