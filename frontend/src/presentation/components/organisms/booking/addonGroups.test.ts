import type { PublicService } from '@application/services/PublicBookingService'

import { addonsTotalOf, groupAddonsByService, withAddonQuantity } from './addonGroups'

const servicio = (
  public_id: string,
  addons: { id: string; name: string; unit_price: number; max_quantity: number }[]
): PublicService =>
  ({
    public_id,
    name: `Servicio ${public_id}`,
    description: null,
    duration_minutes: 30,
    price: 1000,
    deposit_mode: 'none',
    deposit_type: 'fixed',
    deposit_amount: null,
    color: null,
    addons: addons.map((addon, position) => ({ ...addon, position }))
  }) as unknown as PublicService

const catalogo = [
  servicio('corte', [{ id: 'strass', name: 'Strass', unit_price: 500, max_quantity: 10 }]),
  servicio('barba', [{ id: 'brillo', name: 'Brillo', unit_price: 1500, max_quantity: 2 }])
]

// S4 (2026-10-21): los adicionales se eligen en el paso del servicio y el
// wizard guarda las lineas con la misma forma que el paso de confirmacion.
describe('withAddonQuantity', () => {
  it('las lineas del principal van sin serviceId y las de un servicio sumado lo llevan', () => {
    const vacio = groupAddonsByService(['corte', 'barba'], catalogo, [])

    const conStrass = withAddonQuantity(vacio, 'corte', 'strass', 2)
    const conBrillo = withAddonQuantity(
      groupAddonsByService(['corte', 'barba'], catalogo, conStrass),
      'barba',
      'brillo',
      1
    )

    expect(conBrillo).toEqual([
      { addonId: 'strass', name: 'Strass', unitPrice: 500, quantity: 2, amount: 1000 },
      {
        addonId: 'brillo',
        name: 'Brillo',
        unitPrice: 1500,
        quantity: 1,
        amount: 1500,
        serviceId: 'barba'
      }
    ])
  })

  it('poner un adicional en 0 lo saca sin tocar los demas', () => {
    const elegido = withAddonQuantity(
      groupAddonsByService(['corte', 'barba'], catalogo, [
        { addonId: 'strass', name: 'Strass', unitPrice: 500, quantity: 3 },
        { addonId: 'brillo', name: 'Brillo', unitPrice: 1500, quantity: 1, serviceId: 'barba' }
      ]),
      'corte',
      'strass',
      0
    )

    expect(elegido).toEqual([expect.objectContaining({ addonId: 'brillo', serviceId: 'barba' })])
  })
})

describe('addonsTotalOf', () => {
  it('suma los adicionales de todos los servicios elegidos', () => {
    const grupos = groupAddonsByService(['corte', 'barba'], catalogo, [
      { addonId: 'strass', name: 'Strass', unitPrice: 500, quantity: 3 },
      { addonId: 'brillo', name: 'Brillo', unitPrice: 1500, quantity: 1, serviceId: 'barba' }
    ])

    expect(addonsTotalOf(grupos)).toBe(3000)
  })

  it('sin adicionales elegidos es 0', () => {
    expect(addonsTotalOf(groupAddonsByService(['corte'], catalogo, []))).toBe(0)
  })
})
