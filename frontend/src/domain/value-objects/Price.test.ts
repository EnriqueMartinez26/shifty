import { Price } from './Price';

describe('Price Value Object', () => {
  it('debe instanciar un precio válido', () => {
    const price = Price.create(100.50);
    expect(price.getValue()).toBe(100.50);
  });

  it('debe arrojar error si el precio es negativo', () => {
    expect(() => Price.create(-10)).toThrow('El precio no puede ser negativo');
  });

  it('debe formatear a moneda', () => {
    const price = Price.create(1500.5);
    // Intl.NumberFormat es-AR uses non-breaking spaces, so we normalize spaces for testing
    expect(price.format().replace(/\s/g, ' ')).toMatch(/\$\s?1\.500,50/);
  });
});
