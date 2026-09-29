import {
  normalizeSlugInput,
  numberInRange,
  SETTINGS_LIMITS,
  validateSettingsDraft
} from './settingsValidation'

describe('normalizeSlugInput', () => {
  it('pasa a minusculas, espacios a guiones y saca acentos y simbolos', () => {
    expect(normalizeSlugInput('Peluquería  Tucumán!')).toBe('peluqueria-tucuman')
  })

  it('no recorta el guion final mientras se tipea', () => {
    expect(normalizeSlugInput('mi-')).toBe('mi-')
  })
})

describe('validateSettingsDraft', () => {
  it('no valida lo que no esta en el borrador', () => {
    expect(validateSettingsDraft({})).toEqual({})
  })

  it.each(['a', '-local', 'local-', ''])('rechaza el slug %p', (slug) => {
    expect(validateSettingsDraft({ slug }).slug).toBeDefined()
  })

  it.each(['ab', 'mi-local-2', 'a'.repeat(100)])('acepta el slug %p', (slug) => {
    expect(validateSettingsDraft({ slug })).toEqual({})
  })

  it('rechaza 101 caracteres', () => {
    expect(validateSettingsDraft({ slug: 'a'.repeat(101) }).slug).toBeDefined()
  })

  it.each([
    { open: '18:00', close: '18:00' },
    { open: '19:00', close: '09:00' },
    { open: '', close: '18:00' }
  ])('rechaza el periodo %p', (period) => {
    expect(
      validateSettingsDraft({ business_hours: { mon: [period] } }).business_hours
    ).toBeDefined()
  })

  it('rechaza un dia con mas de un periodo aunque no sea el editado', () => {
    const p = { open: '09:00', close: '12:00' }
    const q = { open: '14:00', close: '18:00' }
    expect(
      validateSettingsDraft({ business_hours: { mon: [p, q], tue: [p] } }).business_hours
    ).toMatch(/El Lunes tiene 2 horarios/)
  })

  it('acepta un dia cerrado y uno con apertura antes del cierre', () => {
    expect(
      validateSettingsDraft({
        business_hours: { mon: [], tue: [{ open: '09:00', close: '18:00' }] }
      })
    ).toEqual({})
  })
})

describe('numberInRange', () => {
  const { min, max } = SETTINGS_LIMITS.buffer_minutes

  it('recorta a los topes del backend y vacio es el minimo', () => {
    expect(numberInRange('99999', min, max)).toBe(1440)
    expect(numberInRange('-5', min, max)).toBe(0)
    expect(numberInRange('', min, max)).toBe(0)
  })
})
