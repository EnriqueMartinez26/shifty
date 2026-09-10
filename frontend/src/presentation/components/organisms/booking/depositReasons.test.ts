import { depositReasonsText } from './depositReasons'

describe('depositReasonsText', () => {
  it('explica los recargos en castellano y omite la base', () => {
    expect(depositReasonsText(['base'])).toBe('')
    expect(depositReasonsText(['base', 'new_client'])).toBe('ser tu primera visita')
    expect(depositReasonsText(['base', 'far_notice', 'absences'])).toBe(
      'reservar con mucha antelacion y ausencias anteriores'
    )
    expect(depositReasonsText(['base', 'far_notice', 'new_client', 'absences'])).toBe(
      'reservar con mucha antelacion, ser tu primera visita y ausencias anteriores'
    )
  })
})
