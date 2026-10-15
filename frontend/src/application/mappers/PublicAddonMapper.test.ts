import axios from 'axios'

import { publicAddonOptions } from './PublicAddonMapper'
import type { PublicService } from '../services/PublicBookingService'

const servicio = (addons: PublicService['addons']): PublicService => ({
  public_id: 'svc-1',
  name: 'Uñas',
  description: null,
  duration_minutes: 60,
  price: 27000,
  deposit_mode: 'none',
  deposit_type: 'percent',
  deposit_amount: null,
  color: null,
  image_url: null,
  addons
})

describe('publicAddonOptions', () => {
  it('ordena por posicion y pasa a camelCase', () => {
    expect(
      publicAddonOptions(
        servicio([
          { id: 'b', name: 'Diseño', unit_price: 1500, max_quantity: 2, position: 1 },
          { id: 'a', name: 'Strass', unit_price: 500, max_quantity: 10, position: 0 }
        ])
      )
    ).toEqual([
      { id: 'a', name: 'Strass', unitPrice: 500, maxQuantity: 10 },
      { id: 'b', name: 'Diseño', unitPrice: 1500, maxQuantity: 2 }
    ])
  })

  it('sin servicio o sin adicionales no hay opciones', () => {
    expect(publicAddonOptions(undefined)).toEqual([])
    expect(publicAddonOptions(servicio(undefined))).toEqual([])
  })
})

// El preview de la seña lee `addon` repetido: con el formato por defecto de
// axios (`addon[]=`) FastAPI no veria ningun adicional y la seña saldria sobre
// el precio base.
describe('serializacion de addon en la query', () => {
  it('indexes: null repite la clave sin corchetes', () => {
    const uri = axios.getUri({
      url: '/public/deposit/preview',
      params: { addon: ['strass:6', 'diseno:1'] },
      paramsSerializer: { indexes: null }
    })

    expect(uri).toBe('/public/deposit/preview?addon=strass:6&addon=diseno:1')
  })
})
