import { Price } from './Price'

describe('Price Value Object', () => {
  it('debe instanciar un precio válido', () => {
    const price = Price.create(100.5)
    expect(price.getValue()).toBe(100.5)
  })

  it('debe arrojar error si el precio es negativo', () => {
    expect(() => Price.create(-10)).toThrow('El precio no puede ser negativo')
  })

  it('debe formatear a moneda', () => {
    const price = Price.create(1500.5)
    // Intl.NumberFormat es-AR uses non-breaking spaces, so we normalize spaces for testing
    // Mismo formateador que el resto del front (shared/utils/currency): sin
    // centavos.
    expect(price.format().replace(/\s/g, ' ')).toBe('$ 1.501')
  })
})
