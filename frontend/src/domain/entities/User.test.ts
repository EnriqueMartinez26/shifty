import { User } from './User'

const primitives = {
  id: '01J8ZQ4Y7XKQ3M0B5N6P7R8S9T',
  email: 'ana@example.com',
  firstName: 'Ana',
  lastName: 'Perez',
  phone: '+5491100000000',
  role: 'admin',
  isActive: true,
  createdAt: '2026-09-10T12:00:00.000Z'
}

describe('User.fromPrimitives / toPrimitives', () => {
  it('ida y vuelta conserva la forma primitiva', () => {
    expect(User.fromPrimitives(primitives).toPrimitives()).toEqual(primitives)
  })

  it('un campo que no es del usuario no se cuela en toPrimitives (F8-11)', () => {
    // Antes fromPrimitives y toPrimitives hacian spread: cualquier clave de
    // mas en el objeto de entrada terminaba en el payload de salida.
    const withExtra = { ...primitives, internalNote: 'no viaja' }

    const out = User.fromPrimitives(withExtra).toPrimitives()

    expect(Object.keys(out).sort()).toEqual(Object.keys(primitives).sort())
  })

  it.each([
    ['id vacio', { id: '  ' }],
    ['email invalido', { email: 'no-es-mail' }],
    ['rol desconocido', { role: 'owner' }]
  ])('rechaza %s', (_caso, override) => {
    expect(() => User.fromPrimitives({ ...primitives, ...override })).toThrow()
  })
})

describe('User', () => {
  it.each([
    ['Ana', 'Perez', 'Ana Perez'],
    ['Ana', null, 'Ana'],
    [null, 'Perez', 'Perez'],
    [null, null, 'Sin Nombre']
  ])('fullName(%s, %s) = %s', (firstName, lastName, expected) => {
    const user = User.fromPrimitives({ ...primitives, firstName, lastName })
    expect(user.fullName).toBe(expected)
  })

  it('activate/deactivate cambian isActive', () => {
    const user = User.fromPrimitives(primitives)
    user.deactivate()
    expect(user.isActive).toBe(false)
    user.activate()
    expect(user.isActive).toBe(true)
  })

  it('create asigna id y fecha de alta', () => {
    const user = User.fromPrimitives(primitives)
    const created = User.create({
      email: user.email,
      firstName: 'Ana',
      lastName: null,
      phone: null,
      role: user.role,
      isActive: true
    })
    expect(created.id).not.toBe('')
    expect(created.toPrimitives().createdAt).toMatch(/^\d{4}-\d{2}-\d{2}T/)
  })
})
