import { isValidClientPhone } from './clientPhone'

// Mismo criterio que core/validation.py::normalize_client_phone.
describe('isValidClientPhone', () => {
  it.each(['1155550101', '11 5555-0101', '+54 (11) 5555-0101', '123456'])('acepta %s', (phone) => {
    expect(isValidClientPhone(phone)).toBe(true)
  })

  it.each([
    ['vacio', ''],
    ['QA: tres digitos', '123'],
    ['cinco digitos con separadores', '1-2-3-4-5'],
    ['letras', '11 5555 ABCD'],
    ['punto', '11.5555.0101'],
    ['mas de 30 caracteres', '1'.repeat(31)]
  ])('rechaza %s', (_caso, phone) => {
    expect(isValidClientPhone(phone)).toBe(false)
  })
})
