import { buildWaMeUrl, normalizePhoneForWhatsApp } from './whatsAppPhone'

// 2026-10-02, QA en navegador: un telefono de la lista de espera cargado como
// "11 5555 0303" armaba https://wa.me/1155550303, que WhatsApp lee como un
// numero de Estados Unidos. wa.me exige el numero internacional sin "+", y un
// celular argentino es 54 9 + area + abonado (10 digitos, sin 0 ni 15).
describe('normalizePhoneForWhatsApp', () => {
  it.each([
    ['11 5555 0000', '5491155550000'],
    ['011 15-5555-0000', '5491155550000'],
    ['+54 9 11 5555 0000', '5491155550000'],
    ['5491155550000', '5491155550000'],
    ['351 555-1234', '5493515551234'],
    ['0351 15 555 1234', '5493515551234'],
    ['(011) 5555-0000', '5491155550000'],
    ['+54 9 11 15 5555 0000', '5491155550000'],
    ['+54 11 15 5555 0000', '5491155550000'],
    ['00 54 9 351 555 1234', '5493515551234'],
    ['2964 15 401234', '5492964401234'],
    ['02964 401234', '5492964401234']
  ])('%s -> %s', (raw, expected) => {
    expect(normalizePhoneForWhatsApp(raw)).toBe(expected)
  })

  // Revision R3: con el codigo de pais escrito y sin 9 ni 15 puede ser una
  // linea fija con WhatsApp Business; agregarle el 9 la mandaba a otro numero.
  it('con 54 escrito y sin 9 ni 15 lo respeta tal cual', () => {
    expect(normalizePhoneForWhatsApp('+54 11 4555 0000')).toBe('541145550000')
    expect(normalizePhoneForWhatsApp('541145550000')).toBe('541145550000')
    expect(normalizePhoneForWhatsApp('+54 011 4555 0000')).toBe('541145550000')
  })

  it('respeta un numero que ya trae otro codigo de pais', () => {
    expect(normalizePhoneForWhatsApp('+1 (202) 555-0123')).toBe('12025550123')
    expect(normalizePhoneForWhatsApp('0034 612 345 678')).toBe('34612345678')
  })

  it.each([
    ['vacio', ''],
    ['solo espacios', '   '],
    ['basura', 'llamame al local'],
    ['corto', '123'],
    ['sin codigo de area', '4555-1234'],
    ['largo de mas', '011 5555 0000 1234 5678'],
    ['numero local con 9 adelante', '9 11 5555 0000'],
    ['internacional demasiado corto', '+12 345'],
    ['"+" en el medio', '11 +5555 0000']
  ])('sin confianza devuelve null (%s)', (_caso, raw) => {
    expect(normalizePhoneForWhatsApp(raw)).toBeNull()
  })

  it('null y undefined no rompen', () => {
    expect(normalizePhoneForWhatsApp(null)).toBeNull()
    expect(normalizePhoneForWhatsApp(undefined)).toBeNull()
  })
})

describe('buildWaMeUrl', () => {
  it('arma el link con el numero normalizado y el texto codificado', () => {
    expect(buildWaMeUrl('11 5555 0031', 'Hola & chau')).toBe(
      'https://wa.me/5491155550031?text=Hola%20%26%20chau'
    )
  })

  it('sin un numero confiable no arma link', () => {
    expect(buildWaMeUrl('123', 'Hola')).toBeNull()
  })
})
