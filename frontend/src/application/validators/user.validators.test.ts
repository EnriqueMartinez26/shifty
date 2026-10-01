import { createUserSchema } from './user.validators'

// Cobertura de F9-08 (2026-09-30): el schema no tenia test propio. Es un PR
// solo de tests, verde desde el principio: describe el comportamiento actual.

const minimo = {
  email: 'ana@example.com',
  password: 'doce-chars12',
  role: 'staff'
}

const issuesDe = (input: unknown) => {
  const result = createUserSchema.safeParse(input)
  return result.success ? [] : result.error.issues.map((i) => [i.path.join('.'), i.message])
}

describe('createUserSchema', () => {
  it('el minimo valido pasa sin nombre, apellido ni telefono', () => {
    expect(issuesDe(minimo)).toEqual([])
  })

  it.each([
    ['email invalido', { email: 'ana@' }, 'email', 'Email inválido'],
    [
      'password de 11 caracteres',
      { password: 'once-chars1' },
      'password',
      'La contraseña debe tener al menos 12 caracteres'
    ],
    ['nombre de 101 caracteres', { first_name: 'a'.repeat(101) }, 'first_name', 'Nombre muy largo'],
    [
      'apellido de 101 caracteres',
      { last_name: 'a'.repeat(101) },
      'last_name',
      'Apellido muy largo'
    ],
    ['telefono de 51 caracteres', { phone: '1'.repeat(51) }, 'phone', 'Teléfono muy largo']
  ])('%s falla con su mensaje', (_caso, cambio, campo, mensaje) => {
    expect(issuesDe({ ...minimo, ...cambio })).toEqual([[campo, mensaje]])
  })

  it.each([
    ['password de 12 caracteres', { password: 'a'.repeat(12) }],
    ['nombre de 100 caracteres', { first_name: 'a'.repeat(100) }],
    ['telefono de 50 caracteres', { phone: '1'.repeat(50) }],
    ['first_name undefined', { first_name: undefined }]
  ])('%s pasa', (_caso, cambio) => {
    expect(issuesDe({ ...minimo, ...cambio })).toEqual([])
  })

  it.each(['first_name', 'last_name', 'phone'])(
    '%s vacio falla (el form lo vuelve ausente)',
    (campo) => {
      const campos = issuesDe({ ...minimo, [campo]: '' }).map(([path]) => path)

      expect(campos).toEqual([campo])
    }
  )

  it.each(['admin', 'staff', 'receptionist', 'client'])('el rol %s pasa', (role) => {
    expect(issuesDe({ ...minimo, role })).toEqual([])
  })

  it('el rol superadmin no existe: el alta de superadmin no pasa por aca', () => {
    const campos = issuesDe({ ...minimo, role: 'superadmin' }).map(([path]) => path)

    expect(campos).toEqual(['role'])
  })
})
