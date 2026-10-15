import { ServiceAddon, serviceAddonIssue } from './ServiceAddon'

const primitives = { id: 'add-1', name: 'Strass', unit_price: 500, max_quantity: 10, position: 0 }

describe('serviceAddonIssue', () => {
  it('acepta los extremos validos', () => {
    expect(serviceAddonIssue({ name: 'A', unitPrice: 0, maxQuantity: 1 })).toBeNull()
    expect(serviceAddonIssue({ name: 'A', unitPrice: 1_000_000, maxQuantity: 99 })).toBeNull()
    // 0.1 * 100 no da 10 exacto en coma flotante: no es una fraccion de centavo.
    expect(serviceAddonIssue({ name: 'A', unitPrice: 0.1, maxQuantity: 1 })).toBeNull()
  })

  it.each([
    ['nombre vacio', { name: '   ' }, /nombre/],
    ['nombre de mas de 100', { name: 'x'.repeat(101) }, /100 caracteres/],
    ['precio negativo', { unitPrice: -1 }, /0 a 1\.000\.000/],
    ['precio mayor al tope', { unitPrice: 1_000_000.01 }, /0 a 1\.000\.000/],
    ['precio no finito', { unitPrice: Number.NaN }, /0 a 1\.000\.000/],
    ['fraccion de centavo', { unitPrice: 10.005 }, /centavo/],
    ['maximo 0', { maxQuantity: 0 }, /1 a 99/],
    ['maximo 100', { maxQuantity: 100 }, /1 a 99/],
    ['maximo fraccionario', { maxQuantity: 1.5 }, /1 a 99/]
  ])('rechaza %s', (_caso, override, message) => {
    expect(
      serviceAddonIssue({ name: 'Strass', unitPrice: 500, maxQuantity: 10, ...override })
    ).toMatch(message)
  })
})

describe('ServiceAddon', () => {
  it('ida y vuelta conserva la forma primitiva', () => {
    expect(ServiceAddon.fromPrimitives(primitives).toPrimitives()).toEqual(primitives)
  })

  it('recorta el nombre', () => {
    expect(ServiceAddon.fromPrimitives({ ...primitives, name: '  Strass ' }).name).toBe('Strass')
  })

  it('create arma un adicional sin id con su posicion', () => {
    const addon = ServiceAddon.create({ name: 'Diseño', unitPrice: 1500, maxQuantity: 2 }, 3)

    expect(addon.id).toBeNull()
    expect(addon.position).toBe(3)
    expect(addon.unitPrice).toBe(1500)
    expect(addon.maxQuantity).toBe(2)
  })

  it.each([
    ['id vacio', { id: '' }],
    ['precio negativo', { unit_price: -1 }],
    ['maximo fuera de rango', { max_quantity: 0 }]
  ])('fromPrimitives rechaza %s', (_caso, override) => {
    expect(() => ServiceAddon.fromPrimitives({ ...primitives, ...override })).toThrow(
      expect.objectContaining({ code: 'INVALID_ADDON' })
    )
  })

  it('create rechaza un adicional invalido', () => {
    expect(() => ServiceAddon.create({ name: '', unitPrice: 1, maxQuantity: 1 }, 0)).toThrow(
      expect.objectContaining({ code: 'INVALID_ADDON' })
    )
  })
})
