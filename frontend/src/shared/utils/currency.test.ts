import { formatCurrency } from './currency'

// Intl es-AR separa el signo del numero con un espacio duro.
const plano = (texto: string) => texto.replace(/\s/g, ' ')

// 2026-10-02, QA en navegador: el mismo precio salia "$8500", "$ 4.200" o
// "$1500.0" segun la pantalla. Todo importe pasa por este formateador.
describe('formatCurrency', () => {
  it.each([
    [8500, '$ 8.500'],
    ['4200', '$ 4.200'],
    ['1500.0', '$ 1.500'],
    [0, '$ 0']
  ])('%p se muestra como %p', (valor, esperado) => {
    expect(plano(formatCurrency(valor))).toBe(esperado)
  })

  it('redondea a pesos enteros y respeta el signo', () => {
    expect(plano(formatCurrency(1234.56))).toBe('$ 1.235')
    expect(plano(formatCurrency(-1500))).toBe('-$ 1.500')
  })

  it('un valor ausente o ilegible se muestra como cero, no como "$ NaN"', () => {
    expect(plano(formatCurrency(null))).toBe('$ 0')
    expect(plano(formatCurrency(undefined))).toBe('$ 0')
    expect(plano(formatCurrency(''))).toBe('$ 0')
    expect(plano(formatCurrency('abc'))).toBe('$ 0')
  })

  it('respeta otra moneda', () => {
    expect(plano(formatCurrency(10, 'USD'))).toBe('US$ 10')
  })
})
