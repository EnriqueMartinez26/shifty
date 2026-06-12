import { Email } from './Email'

describe('Email Value Object', () => {
  it('debe crear un email válido', () => {
    const email = Email.create('test@example.com')
    expect(email.getValue()).toBe('test@example.com')
  })

  it('debe normalizar el email a minúsculas y sin espacios', () => {
    const email = Email.create('  TEST@example.COM  ')
    expect(email.getValue()).toBe('test@example.com')
  })

  it('debe arrojar error con formato inválido', () => {
    expect(() => Email.create('invalid-email')).toThrow('Email inválido: invalid-email')
    expect(() => Email.create('@example.com')).toThrow()
  })

  it('debe comparar emails', () => {
    const e1 = Email.create('a@a.com')
    const e2 = Email.create('A@A.COM')
    expect(e1.equals(e2)).toBe(true)
  })
})
