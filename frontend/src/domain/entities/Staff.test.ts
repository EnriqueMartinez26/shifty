import { Staff } from './Staff'

const primitives = {
  public_id: '01J8ZQ4Y7XKQ3M0B5N6P7R8S9T',
  kind: 'person',
  first_name: 'Ana',
  last_name: 'Perez',
  email: 'ana@example.com',
  display_name: null,
  is_active: true,
  service_ids: ['svc-1']
}

describe('Staff.fromPrimitives', () => {
  it('ida y vuelta conserva la forma primitiva', () => {
    expect(Staff.fromPrimitives(primitives).toPrimitives()).toEqual(primitives)
  })

  it.each([
    ['null', null],
    ['vacio', ''],
    ['solo espacios', '   ']
  ])('un recurso con email %s no tumba la pagina de personal (2026-09-10)', (_caso, email) => {
    // Email.create('') explotaba y tiraba abajo la pagina entera de personal.
    const staff = Staff.fromPrimitives({
      ...primitives,
      kind: 'resource',
      first_name: '',
      last_name: '',
      display_name: 'Cancha 1',
      email
    })

    expect(staff.email).toBeNull()
    expect(staff.isResource).toBe(true)
    expect(staff.fullName).toBe('Cancha 1')
  })

  it.each([
    ['resource', 'resource'],
    ['person', 'person'],
    [null, 'person'],
    [undefined, 'person'],
    ['otro', 'person']
  ])('kind %s -> %s', (kind, expected) => {
    expect(Staff.fromPrimitives({ ...primitives, kind }).kind).toBe(expected)
  })

  it('un email presente e invalido se rechaza', () => {
    expect(() => Staff.fromPrimitives({ ...primitives, email: 'no-es-mail' })).toThrow()
  })
})

describe('Staff', () => {
  it.each([
    [null, 'Ana Perez'],
    ['Anita', 'Anita']
  ])('displayName con display_name=%s es %s', (displayName, expected) => {
    const staff = Staff.fromPrimitives({ ...primitives, display_name: displayName })
    expect(staff.displayName).toBe(expected)
  })

  it('asignar y quitar servicios no duplica ni muta la copia expuesta', () => {
    const staff = Staff.fromPrimitives(primitives)
    staff.assignToService('svc-1')
    staff.assignToService('svc-2')
    staff.serviceIds.push('svc-fuera')
    expect(staff.serviceIds).toEqual(['svc-1', 'svc-2'])

    staff.removeFromService('svc-1')
    expect(staff.serviceIds).toEqual(['svc-2'])
  })
})
