import { UserId } from './UserId'

describe('UserId Value Object', () => {
  it('debe instanciar con un valor válido', () => {
    const id = UserId.create('user-123')
    expect(id.getValue()).toBe('user-123')
  })

  it('debe arrojar error si está vacío', () => {
    expect(() => UserId.create('')).toThrow('UserId inválido: no puede estar vacío')
    expect(() => UserId.create('   ')).toThrow('UserId inválido: no puede estar vacío')
  })

  it.each([
    ['ULID del backend', '01J8ZQ4Y7XKQ3M0B5N6P7R8S9T'],
    ['UUID de createUuid', '3f2b8c1e-9a4d-4e6f-8b7a-1c2d3e4f5a6b']
  ])('acepta un %s: el id es opaco (F8-14)', (_origen, value) => {
    expect(UserId.create(value).getValue()).toBe(value)
  })

  it('debe igualar correctamente', () => {
    const id1 = UserId.create('123')
    const id2 = UserId.create('123')
    const id3 = UserId.create('456')

    expect(id1.equals(id2)).toBe(true)
    expect(id1.equals(id3)).toBe(false)
  })
})
