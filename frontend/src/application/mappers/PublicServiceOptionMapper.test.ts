import axios from 'axios'

import {
  publicPerformers,
  publicServiceOptions,
  staffForAllServices
} from './PublicServiceOptionMapper'
import type { PublicService, PublicStaff } from '../services/PublicBookingService'

const servicio = (public_id: string, overrides: Partial<PublicService> = {}): PublicService => ({
  public_id,
  name: `Servicio ${public_id}`,
  description: null,
  duration_minutes: 30,
  price: 1000,
  deposit_mode: 'none',
  deposit_type: 'percent',
  deposit_amount: null,
  color: null,
  image_url: null,
  ...overrides
})

const profesional = (public_id: string, service_ids: string[]): PublicStaff => ({
  public_id,
  first_name: public_id,
  last_name: '',
  display_name: public_id,
  service_ids
})

describe('publicServiceOptions', () => {
  it('pasa a camelCase y a numero (el backend puede mandar el precio como texto)', () => {
    const conPrecioTexto = servicio('a', {
      name: 'Corte',
      duration_minutes: 45,
      price: '1500.50' as unknown as number
    })

    expect(publicServiceOptions([conPrecioTexto])).toEqual([
      { id: 'a', name: 'Corte', durationMinutes: 45, price: 1500.5 }
    ])
  })

  it('sin catalogo no hay opciones', () => {
    expect(publicServiceOptions(undefined)).toEqual([])
  })
})

describe('publicPerformers', () => {
  it('toma los servicios de cada profesional y tolera la lista ausente', () => {
    const sinLista = { ...profesional('x', []), service_ids: undefined } as unknown as PublicStaff

    expect(publicPerformers([profesional('p1', ['a', 'b']), sinLista])).toEqual([
      { serviceIds: ['a', 'b'] },
      { serviceIds: [] }
    ])
  })
})

describe('staffForAllServices', () => {
  const staff = [profesional('p1', ['a', 'b']), profesional('p2', ['a'])]

  it('sin adicionales deja la lista como llego', () => {
    expect(staffForAllServices(staff, [])).toEqual(staff)
  })

  it('con adicionales deja solo a quien hace todos', () => {
    expect(staffForAllServices(staff, ['b']).map((member) => member.public_id)).toEqual(['p1'])
  })
})

// La disponibilidad y los previews leen `extra_service_id` repetido.
describe('serializacion de extra_service_id en la query', () => {
  it('indexes: null repite la clave sin corchetes', () => {
    const uri = axios.getUri({
      url: '/public/availability',
      params: { extra_service_id: ['b', 'c'] },
      paramsSerializer: { indexes: null }
    })

    expect(uri).toBe('/public/availability?extra_service_id=b&extra_service_id=c')
  })
})
