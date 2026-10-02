import { passwordPolicyError } from './passwordPolicy'

// Mismo piso que core/validation.py::validate_password_strength.
describe('passwordPolicyError', () => {
  it('acepta 12 caracteres con letras y numeros', () => {
    expect(passwordPolicyError('Barberia2026')).toBeNull()
  })

  it.each([
    ['corta', 'abc123'],
    ['sin numeros', 'soloLetrasLargas'],
    ['sin letras', '123456789012']
  ])('rechaza una %s', (_caso, password) => {
    expect(passwordPolicyError(password)).toMatch(/al menos 12 caracteres/)
  })
})
