import { formatCurrency, formatPercent, numberFormatter } from './dashboardFormatters'

// F11b-09 (cuarta tajada): los formateadores salieron de `Dashboard.tsx`. Los
// valores esperados son literales es-AR, no se calculan con el codigo bajo
// prueba. `ars` normaliza el espacio duro (U+00A0) que Intl pone entre el
// simbolo y el numero, igual que el `peso` de la caracterizacion de la pagina.

const ars = (value: number | string | null | undefined) =>
  formatCurrency(value).replace(/\s+/g, ' ')

describe('formatCurrency', () => {
  it('formatea un numero en pesos argentinos sin decimales', () => {
    expect(ars(1500)).toBe('$ 1.500')
    expect(ars(450000)).toBe('$ 450.000')
  })

  it('acepta el monto como texto', () => {
    expect(ars('2500')).toBe('$ 2.500')
  })

  it('trata null, undefined y vacio como cero', () => {
    expect(ars(null)).toBe('$ 0')
    expect(ars(undefined)).toBe('$ 0')
    expect(ars('')).toBe('$ 0')
  })

  it('redondea los centavos y respeta el signo', () => {
    expect(ars(1234.56)).toBe('$ 1.235')
    expect(ars(-1500)).toBe('-$ 1.500')
  })
})

describe('formatPercent', () => {
  it('imprime un decimal como mucho, con coma', () => {
    expect(formatPercent(62.5)).toBe('62,5%')
    expect(formatPercent(8.44)).toBe('8,4%')
    expect(formatPercent(12.36)).toBe('12,4%')
  })

  it('no agrega ceros decimales', () => {
    expect(formatPercent(100)).toBe('100%')
    expect(formatPercent(40)).toBe('40%')
  })

  it('trata cero, null y undefined como 0%', () => {
    expect(formatPercent(0)).toBe('0%')
    expect(formatPercent(null)).toBe('0%')
    expect(formatPercent(undefined)).toBe('0%')
  })

  it('respeta el signo negativo', () => {
    expect(formatPercent(-15.7)).toBe('-15,7%')
  })
})

describe('numberFormatter', () => {
  it('no imprime decimales', () => {
    expect(numberFormatter.format(12)).toBe('12')
    expect(numberFormatter.format(12.4)).toBe('12')
    expect(numberFormatter.format(0)).toBe('0')
  })

  it('separa los miles con punto', () => {
    expect(numberFormatter.format(12500)).toBe('12.500')
  })
})
