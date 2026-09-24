import { daysUntil, expiryLabel } from './shared'

// El ida y vuelta de `toDateTimeInput`/`fromDateTimeInput` se prueba en
// `shared/utils/argentinaTime.test.ts`, donde viven los helpers desde que las
// promociones de tienda los necesitaron (2026-09-20).
describe('fechas del superadmin', () => {
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
