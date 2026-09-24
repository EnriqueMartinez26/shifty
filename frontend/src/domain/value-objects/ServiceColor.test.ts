import { ServiceColor } from './ServiceColor'

describe('ServiceColor Value Object', () => {
  it('acepta hex largo (#RRGGBB)', () => {
    expect(ServiceColor.create('#FF00AA').getValue()).toBe('#FF00AA')
  })

  it('acepta hex corto (#RGB), igual que el backend', () => {
    expect(ServiceColor.create('#F0A').getValue()).toBe('#F0A')
  })

  it('acepta minúsculas en ambos formatos', () => {
    expect(ServiceColor.create('#ff00aa').getValue()).toBe('#ff00aa')
    expect(ServiceColor.create('#f0a').getValue()).toBe('#f0a')
  })

  it('rechaza valores sin el largo correcto', () => {
    expect(() => ServiceColor.create('#FF00A')).toThrow('Color hexadecimal inválido: #FF00A')
    expect(() => ServiceColor.create('FF00AA')).toThrow('Color hexadecimal inválido: FF00AA')
    expect(() => ServiceColor.create('')).toThrow('Color hexadecimal inválido: ')
  })

  it('compara colores sin distinguir mayúsculas', () => {
    const a = ServiceColor.create('#FF00AA')
    const b = ServiceColor.create('#ff00aa')
    expect(a.equals(b)).toBe(true)
  })
})
