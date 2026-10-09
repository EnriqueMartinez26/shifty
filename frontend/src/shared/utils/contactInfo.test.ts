import { getContactInfo, parseContactInfo, supportWhatsAppUrl } from './contactInfo'
import { getContactEnv } from './env'

// Valores de prueba: los reales se cargan como variables del repo en GitHub y
// nunca van al codigo (el repo es publico).
const completo = {
  supportWhatsApp: '5493510000000',
  contactEmail: 'responsable@example.com',
  legalResponsables: 'Persona Responsable Uno y Persona Responsable Dos'
}

describe('parseContactInfo', () => {
  it('con todo configurado devuelve los tres datos normalizados', () => {
    expect(parseContactInfo(completo)).toEqual({
      responsables: 'Persona Responsable Uno y Persona Responsable Dos',
      email: 'responsable@example.com',
      whatsAppNumber: '5493510000000'
    })
  })

  it('sin nada configurado no inventa nada', () => {
    expect(parseContactInfo({})).toEqual({ responsables: null, email: null, whatsAppNumber: null })
  })

  it('recorta espacios y deja afuera los vacios', () => {
    expect(
      parseContactInfo({ supportWhatsApp: '   ', contactEmail: ' ', legalResponsables: '  Ana  ' })
    ).toEqual({ responsables: 'Ana', email: null, whatsAppNumber: null })
  })

  it.each([['no-es-un-email'], ['dos@arrobas@example.com'], ['con espacio@example.com'], ['a@b']])(
    'un email invalido (%s) no se muestra',
    (email) => {
      expect(parseContactInfo({ contactEmail: email }).email).toBeNull()
    }
  )

  it.each([['[[COMPLETAR]]'], ['pendiente'], ['PENDIENTE'], ['change_me']])(
    'un placeholder (%s) cuenta como no configurado',
    (valor) => {
      expect(
        parseContactInfo({ legalResponsables: valor, contactEmail: valor, supportWhatsApp: valor })
      ).toEqual({ responsables: null, email: null, whatsAppNumber: null })
    }
  )

  it('normaliza el WhatsApp con el helper de wa.me y descarta uno ilegible', () => {
    expect(parseContactInfo({ supportWhatsApp: '+54 9 351 000-0000' }).whatsAppNumber).toBe(
      '5493510000000'
    )
    expect(parseContactInfo({ supportWhatsApp: '12' }).whatsAppNumber).toBeNull()
    expect(parseContactInfo({ supportWhatsApp: 'abc' }).whatsAppNumber).toBeNull()
  })
})

describe('getContactInfo y supportWhatsAppUrl', () => {
  afterEach(() => {
    jest.mocked(getContactEnv).mockReturnValue({})
  })

  it('leen la configuracion del build', () => {
    jest.mocked(getContactEnv).mockReturnValue(completo)

    expect(getContactInfo().email).toBe('responsable@example.com')
    expect(supportWhatsAppUrl('Hola')).toBe('https://wa.me/5493510000000?text=Hola')
  })

  it('sin WhatsApp configurado no hay link', () => {
    expect(supportWhatsAppUrl('Hola')).toBeNull()
  })
})
