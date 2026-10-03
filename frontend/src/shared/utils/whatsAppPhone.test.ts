import { buildWaMeUrl, normalizePhoneForWhatsApp } from './whatsAppPhone'
import casos from './whatsAppPhone.cases.json'

// 2026-10-02, QA en navegador: un telefono de la lista de espera cargado como
// "11 5555 0303" armaba https://wa.me/1155550303, que WhatsApp lee como un
// numero de Estados Unidos. wa.me exige el numero internacional sin "+", y un
// celular argentino es 54 9 + area + abonado (10 digitos, sin 0 ni 15).
//
// Los casos viven en `whatsAppPhone.cases.json` y los lee tambien el test del
// port de Python (`backend/tests/unit/test_whatsapp_phone.py`, sobre
// `backend/core/whatsapp_phone.py`): el backend decide con la misma regla si
// el WhatsApp de la tienda es un canal para cobrar la sena. Revision 4R de la
// PR #108: el NBSP pasaba aca y no alla; ahora hay casos de NBSP, espacio fino
// y BOM en el archivo compartido.
describe('normalizePhoneForWhatsApp', () => {
  it.each(casos.normalizes.map(({ raw, expected }) => [raw, expected]))(
    '%j -> %s',
    (raw, expected) => {
      expect(normalizePhoneForWhatsApp(raw)).toBe(expected)
    }
  )

  it.each(casos.rejects.map(({ case: caso, raw }) => [caso, raw]))(
    'sin confianza devuelve null (%s)',
    (_caso, raw) => {
      expect(normalizePhoneForWhatsApp(raw)).toBeNull()
    }
  )

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
