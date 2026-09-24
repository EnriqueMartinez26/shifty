import type { AxiosInstance } from 'axios'

import { HttpBookingRepository } from './HttpBookingRepository'

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

  it('un turno con un estado desconocido no tumba la lista (F8-03)', async () => {
    const results = [
      appointmentDto(1),
      { ...appointmentDto(2), status: 'on_hold' },
      appointmentDto(3)
    ]
    const get = jest.fn().mockResolvedValue({ data: { total: 3, results } })
    const repository = new HttpBookingRepository({ get } as unknown as AxiosInstance)

    const range = await repository.searchByDateRange('2026-09-01', '2026-09-30')

    expect(range.appointments.map((appointment) => appointment.status)).toEqual([
      'confirmed',
      'on_hold',
      'confirmed'
    ])
  })
})

describe('HttpBookingRepository.create', () => {
  const payload = {
    service_id: 'service-1',
    starts_at: '2026-09-10T12:00:00Z',
    client_name: 'Ana',
    client_phone: '1155550101'
  }

  it('publica el turno y devuelve la entidad', async () => {
    const post = jest.fn().mockResolvedValue({ data: appointmentDto(1) })
    const repository = new HttpBookingRepository({ post } as unknown as AxiosInstance)

    const created = await repository.create(payload)

    expect(post).toHaveBeenCalledWith('/public/appointments', payload)
    expect(created.id).toBe('appt-1')
  })

  it('traduce un error imprevisto a InternalServerError con la operacion', async () => {
    const post = jest.fn().mockRejectedValue(new Error('socket hang up'))
    const repository = new HttpBookingRepository({ post } as unknown as AxiosInstance)

    await expect(repository.create(payload)).rejects.toThrow(
      "Database operation 'create' failed: socket hang up"
    )
  })
})
