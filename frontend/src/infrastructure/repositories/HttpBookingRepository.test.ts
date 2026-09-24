import type { AxiosInstance } from 'axios'

import { HttpBookingRepository } from './HttpBookingRepository'
import { InternalServerError } from '../../shared/errors/InternalServerError'

describe('HttpBookingRepository.findAll', () => {
  afterEach(() => {
    jest.useRealTimers()
  })

  it('pide el rango en dias argentinos, no en el dia UTC (F10-10)', async () => {
    // 22:30 del 15 en Argentina ya es el 16 en UTC.
    jest.useFakeTimers().setSystemTime(new Date('2026-09-16T01:30:00Z'))
    const get = jest.fn().mockResolvedValue({ data: { results: [] } })
    const repository = new HttpBookingRepository({ get } as unknown as AxiosInstance)

    await repository.findAll()

    expect(get).toHaveBeenCalledWith(
      '/appointments/search',
      expect.objectContaining({
        params: expect.objectContaining({ from_date: '2026-08-16', to_date: '2026-09-15' })
      })
    )
  })
})

const appointmentDto = (index: number) => ({
  public_id: `appt-${index}`,
  service_id: 'service-1',
  service_name: 'Corte',
  staff_id: 'staff-1',
  client_name: 'Ana',
  starts_at: '2026-09-10T12:00:00Z',
  ends_at: '2026-09-10T12:30:00Z',
  status: 'confirmed',
  notes: null
})

const page = (size: number, total: number) => ({
  data: { total, results: Array.from({ length: size }, (_, i) => appointmentDto(i)) }
})

describe('HttpBookingRepository.searchByDateRange', () => {
  it('con mas turnos que el tope de paginas devuelve el total del servidor (F10-12)', async () => {
    // 5.100 turnos: el tope de 50 paginas de 100 trae 5.000 y el llamador
    // tiene que poder ver que faltan 100, no recibir la lista como completa.
    const get = jest.fn().mockResolvedValue(page(100, 5100))
    const repository = new HttpBookingRepository({ get } as unknown as AxiosInstance)

    const range = await repository.searchByDateRange('2026-09-01', '2026-09-30')

    expect(get).toHaveBeenCalledTimes(50)
    expect(range.appointments).toHaveLength(5000)
    expect(range.total).toBe(5100)
  })

  it('corta cuando ya tiene el total, sin pedir una pagina vacia de mas', async () => {
    const get = jest.fn().mockResolvedValue(page(100, 200))
    const repository = new HttpBookingRepository({ get } as unknown as AxiosInstance)

    const range = await repository.searchByDateRange('2026-09-01', '2026-09-30')

    expect(get).toHaveBeenCalledTimes(2)
    expect(range).toMatchObject({ total: 200 })
    expect(range.appointments).toHaveLength(200)
  })
})

describe('HttpBookingRepository: CRUD que el backend no expone (F10-05)', () => {
  it.each([
    ['findById', (repository: HttpBookingRepository) => repository.findById('appt-1')],
    ['update', (repository: HttpBookingRepository) => repository.update('appt-1', {})],
    ['delete', (repository: HttpBookingRepository) => repository.delete('appt-1')]
  ])('%s rechaza sin tocar la red', async (_, call) => {
    const client = { get: jest.fn(), patch: jest.fn(), put: jest.fn(), delete: jest.fn() }
    const repository = new HttpBookingRepository(client as unknown as AxiosInstance)

    await expect(call(repository)).rejects.toBeInstanceOf(InternalServerError)

    expect(client.get).not.toHaveBeenCalled()
    expect(client.patch).not.toHaveBeenCalled()
    expect(client.put).not.toHaveBeenCalled()
    expect(client.delete).not.toHaveBeenCalled()
  })
})
