// F9-08 (2026-09-30): cobertura de la reserva publica. Paths literales
// (regla 23), verbo y params de axios tal como los manda hoy el servicio.
const mockGet = jest.fn()
const mockPost = jest.fn()
const mockPatch = jest.fn()

jest.mock('@infrastructure/http/client', () => ({
  __esModule: true,
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    patch: (...args: unknown[]) => mockPatch(...args)
  }
}))

import { publicBookingService } from './PublicBookingService'

describe('PublicBookingService.getServices', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockGet.mockResolvedValue({ data: [] })
  })

  it('por defecto pide solo la tienda (la URL que cachea el edge)', async () => {
    await publicBookingService.getServices('st-1')

    expect(mockGet).toHaveBeenCalledWith('/public/services', {
      params: { store_public_id: 'st-1' }
    })
  })

  it('fresh agrega un parametro distinto en cada pedido para saltear los caches', async () => {
    const now = jest.spyOn(Date, 'now').mockReturnValueOnce(1).mockReturnValueOnce(2)
    await publicBookingService.getServices('st-1', { fresh: true })
    await publicBookingService.getServices('st-1', { fresh: true })
    now.mockRestore()

    expect(mockGet).toHaveBeenNthCalledWith(1, '/public/services', {
      params: { store_public_id: 'st-1', fresh: 1 }
    })
    expect(mockGet).toHaveBeenNthCalledWith(2, '/public/services', {
      params: { store_public_id: 'st-1', fresh: 2 }
    })
  })
})

describe('PublicBookingService', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockPost.mockReset()
    mockPatch.mockReset()
    mockGet.mockResolvedValue({ data: [] })
    mockPost.mockResolvedValue({ data: {} })
    mockPatch.mockResolvedValue({ data: {} })
  })

  it('previewDeposit manda telefono y codigo cuando vienen', async () => {
    await publicBookingService.previewDeposit({
      storePublicId: 'st-1',
      serviceId: 'svc-1',
      startsAt: '2026-10-01T13:00:00Z',
      clientPhone: '1155550000',
      promotionCode: 'OFF10'
    })

    expect(mockGet).toHaveBeenCalledWith('/public/deposit/preview', {
      params: {
        store_public_id: 'st-1',
        service_id: 'svc-1',
        starts_at: '2026-10-01T13:00:00Z',
        client_phone: '1155550000',
        promotion_code: 'OFF10',
        addon: undefined
      },
      paramsSerializer: { indexes: null }
    })
  })

  it('previewDeposit manda cada adicional como addon=<id>:<cantidad> repetido', async () => {
    await publicBookingService.previewDeposit({
      storePublicId: 'st-1',
      serviceId: 'svc-1',
      startsAt: '2026-10-01T13:00:00Z',
      addons: ['strass:6', 'diseno:1']
    })

    expect(mockGet).toHaveBeenCalledWith('/public/deposit/preview', {
      params: expect.objectContaining({ addon: ['strass:6', 'diseno:1'] }),
      paramsSerializer: { indexes: null }
    })
  })

  it('previewDeposit omite client_phone y promotion_code vacios', async () => {
    await publicBookingService.previewDeposit({
      storePublicId: 'st-1',
      serviceId: 'svc-1',
      startsAt: '2026-10-01T13:00:00Z',
      clientPhone: '',
      promotionCode: ''
    })

    expect(mockGet).toHaveBeenCalledWith('/public/deposit/preview', {
      params: {
        store_public_id: 'st-1',
        service_id: 'svc-1',
        starts_at: '2026-10-01T13:00:00Z',
        client_phone: undefined,
        promotion_code: undefined,
        addon: undefined
      },
      paramsSerializer: { indexes: null }
    })
  })

  it.each([
    ['con', 'svc-1'],
    ['sin', undefined]
  ])('getStaff %s service_id', async (_caso, serviceId) => {
    await publicBookingService.getStaff('st-1', serviceId)

    expect(mockGet).toHaveBeenCalledWith('/public/staff', {
      params: { store_public_id: 'st-1', service_id: serviceId }
    })
  })

  it.each([
    [undefined, false],
    [true, true]
  ])('getAvailability con forceAll=%s manda force_all=%s', async (forceAll, sent) => {
    await publicBookingService.getAvailability('st-1', 'svc-1', '2026-10-01', forceAll)

    expect(mockGet).toHaveBeenCalledWith('/public/availability', {
      params: {
        store_public_id: 'st-1',
        service_id: 'svc-1',
        date: '2026-10-01',
        force_all: sent
      }
    })
  })

  it('createBooking manda el payload por POST y devuelve la confirmacion', async () => {
    const payload = {
      store_public_id: 'st-1',
      service_id: 'svc-1',
      starts_at: '2026-10-01T13:00:00Z',
      idempotency_key: 'idem-1',
      client_name: 'Ana Diaz',
      client_email: 'ana@example.com',
      client_phone: '1155550000'
    }
    const confirmation = { public_id: 'apt-1', status: 'confirmed' }
    mockPost.mockResolvedValue({ data: confirmation })

    await expect(publicBookingService.createBooking(payload)).resolves.toEqual(confirmation)
    expect(mockPost).toHaveBeenCalledWith('/public/appointments', payload)
  })

  it('getStoreRef pide la referencia de la tienda por slug (FF-16)', async () => {
    // FF-16 (2026-10-01): "Mis turnos" resolvia la tienda por la vitrina, que
    // da 404 con la tienda suspendida; el ref responde 200 tambien entonces.
    const ref = { store_public_id: 'store-1', name: 'Sol', accepts_new_bookings: false }
    mockGet.mockResolvedValue({ data: ref })

    await expect(publicBookingService.getStoreRef('sol')).resolves.toEqual(ref)
    expect(mockGet).toHaveBeenCalledWith('/public/stores/sol/ref')
  })

  it('cancelClientAppointment manda el telefono por PATCH', async () => {
    await publicBookingService.cancelClientAppointment('apt-1', '1155550000')

    expect(mockPatch).toHaveBeenCalledWith('/public/client/appointments/apt-1/cancel', {
      phone: '1155550000'
    })
  })

  it('rescheduleClientAppointment manda telefono, horario nuevo y clave por PATCH', async () => {
    await publicBookingService.rescheduleClientAppointment({
      publicId: 'apt-1',
      phone: '1155550000',
      newStartsAt: '2026-10-02T14:00:00Z',
      idempotencyKey: 'idem-2'
    })

    expect(mockPatch).toHaveBeenCalledWith('/public/client/appointments/apt-1/reschedule', {
      phone: '1155550000',
      new_starts_at: '2026-10-02T14:00:00Z',
      idempotency_key: 'idem-2'
    })
  })

  it('requestOtp pide el codigo por POST con canal email', async () => {
    const payload = {
      store_public_id: 'st-1',
      phone: '1155550000',
      channel: 'email' as const,
      email: 'ana@example.com'
    }

    await publicBookingService.requestOtp(payload)

    expect(mockPost).toHaveBeenCalledWith('/public/otp/request', payload)
  })

  it('verifyOtp valida el codigo por POST', async () => {
    const payload = { store_public_id: 'st-1', phone: '1155550000', code: '123456' }

    await publicBookingService.verifyOtp(payload)

    expect(mockPost).toHaveBeenCalledWith('/public/otp/verify', payload)
  })

  it('unsubscribeFromMarketing manda el token en el cuerpo de un POST', async () => {
    await publicBookingService.unsubscribeFromMarketing('t.o.k.en')

    expect(mockPost).toHaveBeenCalledWith('/public/unsubscribe', { token: 't.o.k.en' })
    expect(mockGet).not.toHaveBeenCalled()
  })
})
