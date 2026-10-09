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

describe('HttpBookingRepository.reschedule', () => {
  it('manda el nuevo inicio y la clave del llamador, sin el flag si no se pidio', async () => {
    const patch = jest.fn().mockResolvedValue({ data: {} })
    const repository = new HttpBookingRepository({ patch } as unknown as AxiosInstance)

    await repository.reschedule('appt-1', {
      newStartsAt: '2026-09-10T12:00:00Z',
      idempotencyKey: 'clave-del-formulario-1',
      allowOutsideSchedule: false
    })

    expect(patch).toHaveBeenCalledWith('/appointments/appt-1/reschedule', {
      new_starts_at: '2026-09-10T12:00:00Z',
      idempotency_key: 'clave-del-formulario-1'
    })
  })

  it('manda allow_outside_schedule solo cuando el administrador lo pide (D-20260929-04)', async () => {
    const patch = jest.fn().mockResolvedValue({ data: {} })
    const repository = new HttpBookingRepository({ patch } as unknown as AxiosInstance)

    await repository.reschedule('appt-1', {
      newStartsAt: '2026-09-10T12:00:00Z',
      idempotencyKey: 'clave-del-formulario-1',
      allowOutsideSchedule: true
    })

    expect(patch).toHaveBeenCalledWith('/appointments/appt-1/reschedule', {
      new_starts_at: '2026-09-10T12:00:00Z',
      idempotency_key: 'clave-del-formulario-1',
      allow_outside_schedule: true
    })
  })
})

describe('HttpBookingRepository.searchByDateRange en paralelo (F4-07)', () => {
  it('pide la primera pagina y despues todas las demas juntas', async () => {
    let pending = 0
    let maxPending = 0
    const get = jest.fn().mockImplementation(async () => {
      pending += 1
      maxPending = Math.max(maxPending, pending)
      await Promise.resolve()
      pending -= 1
      return page(100, 300)
    })
    const repository = new HttpBookingRepository({ get } as unknown as AxiosInstance)

    const range = await repository.searchByDateRange('2026-09-01', '2026-09-30')

    expect(get).toHaveBeenCalledTimes(3)
    expect(get.mock.calls.map(([, config]) => config.params.page)).toEqual([1, 2, 3])
    expect(maxPending).toBe(2)
    expect(range.appointments).toHaveLength(300)
  })

  it('una primera pagina corta no pide ninguna otra', async () => {
    const get = jest.fn().mockResolvedValue(page(30, 30))
    const repository = new HttpBookingRepository({ get } as unknown as AxiosInstance)

    const range = await repository.searchByDateRange('2026-09-01', '2026-09-30')

    expect(get).toHaveBeenCalledTimes(1)
    expect(range).toMatchObject({ total: 30 })
  })
})

describe('HttpBookingRepository.create', () => {
  const payload = {
    service_id: 'service-1',
    starts_at: '2026-09-10T12:00:00Z',
    client_name: 'Ana',
    client_phone: '1155550101',
    idempotency_key: 'clave-del-formulario-1'
  }

  it('crea por el alta del panel con la clave del llamador y devuelve el id (FF-04)', async () => {
    // Iba a /public/appointments, que exige accepts_terms: el panel recibia 422.
    const post = jest.fn().mockResolvedValue({ data: { public_id: 'appt-1' } })
    const repository = new HttpBookingRepository({ post } as unknown as AxiosInstance)

    const createdId = await repository.create(payload)

    expect(post).toHaveBeenCalledWith('/appointments/', payload)
    expect(createdId).toBe('appt-1')
  })

  it('traduce un error imprevisto a InternalServerError con la operacion', async () => {
    const post = jest.fn().mockRejectedValue(new Error('socket hang up'))
    const repository = new HttpBookingRepository({ post } as unknown as AxiosInstance)

    await expect(repository.create(payload)).rejects.toMatchObject({
      message: 'No se pudo completar la operación.',
      context: {
        operation: 'create',
        technicalMessage: "Database operation 'create' failed: socket hang up"
      }
    })
  })
})
