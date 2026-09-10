import { daysUntil, expiryLabel, fromDateTimeInput, toDateTimeInput } from './shared'

describe('fechas del superadmin', () => {
  it('el input datetime-local va y vuelve en hora argentina sin deriva', () => {
    // 2026-09-20 15:30 en Buenos Aires = 18:30 UTC.
    expect(toDateTimeInput('2026-09-20T18:30:00+00:00')).toBe('2026-09-20T15:30')
    expect(fromDateTimeInput('2026-09-20T15:30')).toBe('2026-09-20T18:30:00.000Z')
    expect(fromDateTimeInput('')).toBeNull()
    expect(toDateTimeInput(null)).toBe('')
  })

  it('cuenta dias de calendario hasta el vencimiento', () => {
    const hoy = new Date()
    const enTres = new Date(hoy.getTime() + 3 * 86_400_000).toISOString()
    expect(daysUntil(enTres)).toBe(3)
    expect(expiryLabel(enTres)).toBe('Vence en 3 d')
    expect(expiryLabel(null)).toBe('Sin vencimiento')
    const hace2 = new Date(hoy.getTime() - 2 * 86_400_000).toISOString()
    expect(expiryLabel(hace2)).toBe('Vencida hace 2 d')
  })
})
