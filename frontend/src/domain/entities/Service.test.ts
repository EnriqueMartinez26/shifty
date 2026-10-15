import { Service } from './Service'

const primitives = {
  id: '01J8ZQ4Y7XKQ3M0B5N6P7R8S9T',
  name: 'Corte',
  description: null,
  duration_minutes: 30,
  price: 5000,
  color: '#ff0000',
  image_url: null,
  youtube_trailer_url: null,
  deposit_mode: 'required' as const,
  deposit_type: 'percent' as const,
  deposit_amount: 20,
  is_active: true,
  addons: [{ id: 'add-1', name: 'Strass', unit_price: 500, max_quantity: 10, position: 0 }]
}

describe('Service.fromPrimitives', () => {
  it('ida y vuelta conserva la forma primitiva, incluida la sena', () => {
    expect(Service.fromPrimitives(primitives).toPrimitives()).toEqual(primitives)
  })

  it.each([
    ['null', null],
    ['vacio', '']
  ])('sin color (%s) usa el color por defecto', (_caso, color) => {
    expect(Service.fromPrimitives({ ...primitives, color }).color).toBe('#6366f1')
  })

  it.each([
    ['duracion 0', { duration_minutes: 0 }],
    ['duracion mayor a 8 horas', { duration_minutes: 481 }],
    ['precio negativo', { price: -1 }],
    ['color que no es hex', { color: 'rojo' }],
    ['id vacio', { id: '' }]
  ])('rechaza %s', (_caso, override) => {
    expect(() => Service.fromPrimitives({ ...primitives, ...override })).toThrow()
  })
})

describe('Service: adicionales', () => {
  it('ordena los adicionales por posicion', () => {
    const service = Service.fromPrimitives({
      ...primitives,
      addons: [
        { id: 'b', name: 'Diseño', unit_price: 1500, max_quantity: 2, position: 1 },
        { id: 'a', name: 'Strass', unit_price: 500, max_quantity: 10, position: 0 }
      ]
    })

    expect(service.addons.map((addon) => addon.name)).toEqual(['Strass', 'Diseño'])
  })

  it('sin la lista de adicionales queda vacia', () => {
    expect(Service.fromPrimitives({ ...primitives, addons: undefined }).addons).toEqual([])
  })
})
