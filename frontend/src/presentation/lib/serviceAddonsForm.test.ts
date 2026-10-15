import { ServiceAddon } from '@domain/entities/ServiceAddon'

import { addonsChanged, toAddonFormValues } from './serviceAddonsForm'

const guardados = [
  ServiceAddon.fromPrimitives({
    id: 'add-1',
    name: 'Strass',
    unit_price: 500,
    max_quantity: 10,
    position: 0
  }),
  ServiceAddon.fromPrimitives({
    id: 'add-2',
    name: 'Diseño',
    unit_price: 1500,
    max_quantity: 2,
    position: 1
  })
]

describe('toAddonFormValues', () => {
  it('conserva el id y lo usa como key', () => {
    expect(toAddonFormValues(guardados)).toEqual([
      { key: 'add-1', id: 'add-1', name: 'Strass', unitPrice: 500, maxQuantity: 10 },
      { key: 'add-2', id: 'add-2', name: 'Diseño', unitPrice: 1500, maxQuantity: 2 }
    ])
  })

  it('un adicional sin guardar recibe una key nueva y id null', () => {
    const nuevo = ServiceAddon.create({ name: 'Esmalte', unitPrice: 900, maxQuantity: 1 }, 0)
    const [fila] = toAddonFormValues([nuevo])
    expect(fila?.id).toBeNull()
    expect(fila?.key).toEqual(expect.any(String))
  })
})

describe('addonsChanged', () => {
  const filas = () => toAddonFormValues(guardados)

  it('la misma lista no cambio', () => {
    expect(addonsChanged(guardados, filas())).toBe(false)
  })

  it('espacios alrededor del nombre no cuentan como cambio', () => {
    const [primera, segunda] = filas()
    expect(addonsChanged(guardados, [{ ...primera!, name: ' Strass ' }, segunda!])).toBe(false)
  })

  it.each([
    ['otro orden', (f: ReturnType<typeof filas>) => [f[1]!, f[0]!]],
    ['una baja', (f: ReturnType<typeof filas>) => [f[0]!]],
    [
      'un alta',
      (f: ReturnType<typeof filas>) => [
        ...f,
        { key: 'x', id: null, name: 'Esmalte', unitPrice: 900, maxQuantity: 1 }
      ]
    ],
    ['otro nombre', (f: ReturnType<typeof filas>) => [{ ...f[0]!, name: 'Strass dorado' }, f[1]!]],
    ['otro precio', (f: ReturnType<typeof filas>) => [{ ...f[0]!, unitPrice: 600 }, f[1]!]],
    ['otro maximo', (f: ReturnType<typeof filas>) => [{ ...f[0]!, maxQuantity: 5 }, f[1]!]]
  ])('%s es un cambio', (_caso, editar) => {
    expect(addonsChanged(guardados, editar(filas()))).toBe(true)
  })
})
