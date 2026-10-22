// Limpieza de reservas del portal (S6, antiabuso). Paths literales sin barra
// final: el backend corre con redirect_slashes=False (regla 23).
const mockGet = jest.fn()
const mockPost = jest.fn()

jest.mock('@infrastructure/http/client', () => ({
  __esModule: true,
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args)
  }
}))

import { portalBookingsService } from './PortalBookingsService'

const reserva = {
  public_id: 'apt-1',
  client_name: 'Lucia',
  client_phone: '5491155550101',
  service_name: 'Corte',
  staff_name: 'Ana',
  starts_at: '2026-10-25T13:00:00Z',
  created_at: '2026-10-22T10:00:00Z',
  status: 'pending'
}

describe('PortalBookingsService', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockPost.mockReset()
  })

  it('listRecent pide las reservas del portal de la ventana en horas', async () => {
    mockGet.mockResolvedValue({ data: [reserva] })

    const result = await portalBookingsService.listRecent(72)

    expect(mockGet).toHaveBeenCalledWith('/appointments/recent-portal', {
      params: { hours: 72 }
    })
    expect(result).toEqual([reserva])
  })

  it('listRecent devuelve una lista vacia si el backend no manda un array', async () => {
    mockGet.mockResolvedValue({ data: null })

    await expect(portalBookingsService.listRecent(24)).resolves.toEqual([])
  })

  it('bulkCancel manda los ids y el motivo recortado', async () => {
    mockPost.mockResolvedValue({ data: { cancelled: ['apt-1'], skipped: [] } })

    const result = await portalBookingsService.bulkCancel(['apt-1', 'apt-2'], '  Reservas falsas ')

    expect(mockPost).toHaveBeenCalledWith('/appointments/bulk-cancel', {
      appointment_ids: ['apt-1', 'apt-2'],
      reason: 'Reservas falsas'
    })
    expect(result).toEqual({ cancelled: ['apt-1'], skipped: [] })
  })

  it('bulkCancel sin motivo no manda el campo', async () => {
    mockPost.mockResolvedValue({
      data: { cancelled: [], skipped: [{ id: 'apt-1', code: 'APPOINTMENT_ALREADY_CANCELLED' }] }
    })

    const result = await portalBookingsService.bulkCancel(['apt-1'], '   ')

    expect(mockPost).toHaveBeenCalledWith('/appointments/bulk-cancel', {
      appointment_ids: ['apt-1']
    })
    expect(result.skipped).toEqual([{ id: 'apt-1', code: 'APPOINTMENT_ALREADY_CANCELLED' }])
  })

  it('bulkCancel parte mas de 100 ids en tandas (tope del backend) y junta los resultados', async () => {
    const ids = Array.from({ length: 150 }, (_, index) => `apt-${index}`)
    mockPost
      .mockResolvedValueOnce({ data: { cancelled: ids.slice(0, 100), skipped: [] } })
      .mockResolvedValueOnce({
        data: { cancelled: ids.slice(100, 149), skipped: [{ id: 'apt-149', code: 'X' }] }
      })

    const result = await portalBookingsService.bulkCancel(ids, 'Bot')

    expect(mockPost).toHaveBeenCalledTimes(2)
    expect(mockPost).toHaveBeenNthCalledWith(1, '/appointments/bulk-cancel', {
      appointment_ids: ids.slice(0, 100),
      reason: 'Bot'
    })
    expect(mockPost).toHaveBeenNthCalledWith(2, '/appointments/bulk-cancel', {
      appointment_ids: ids.slice(100),
      reason: 'Bot'
    })
    expect(result.cancelled).toEqual(ids.slice(0, 149))
    expect(result.skipped).toEqual([{ id: 'apt-149', code: 'X' }])
  })

  it('bulkCancel completa listas ausentes del resultado', async () => {
    mockPost.mockResolvedValue({ data: {} })

    await expect(portalBookingsService.bulkCancel(['apt-1'])).resolves.toEqual({
      cancelled: [],
      skipped: []
    })
  })
})
