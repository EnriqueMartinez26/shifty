// F9-08 (2026-09-30): cobertura de pagos. Paths literales (regla 23), verbo y
// params de axios tal como los manda hoy el servicio.
const mockGet = jest.fn()
const mockPost = jest.fn()
const mockDelete = jest.fn()

jest.mock('@infrastructure/http/client', () => ({
  __esModule: true,
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    delete: (...args: unknown[]) => mockDelete(...args)
  }
}))

import { paymentsService } from './PaymentsService'

describe('PaymentsService', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockPost.mockReset()
    mockDelete.mockReset()
    mockGet.mockResolvedValue({ data: {} })
    mockPost.mockResolvedValue({ data: {} })
    mockDelete.mockResolvedValue({ data: {} })
  })

  it('getGatewayConfig pide la configuracion por GET y devuelve data', async () => {
    const config = { provider: 'mercadopago', configured: true, oauth_supported: true }
    mockGet.mockResolvedValue({ data: config })

    await expect(paymentsService.getGatewayConfig()).resolves.toEqual(config)
    expect(mockGet).toHaveBeenCalledWith('/payments/gateway-config')
  })

  it('startMercadoPagoOAuth arranca el OAuth por POST sin cuerpo', async () => {
    await paymentsService.startMercadoPagoOAuth()

    expect(mockPost).toHaveBeenCalledWith('/payments/mercadopago/oauth/start')
  })

  it('refreshMercadoPagoOAuth renueva la conexion por POST sin cuerpo', async () => {
    await paymentsService.refreshMercadoPagoOAuth()

    expect(mockPost).toHaveBeenCalledWith('/payments/mercadopago/oauth/refresh')
  })

  it('disconnectMercadoPagoOAuth borra la conexion por DELETE', async () => {
    mockDelete.mockResolvedValue({ data: { disconnected: true } })

    await expect(paymentsService.disconnectMercadoPagoOAuth()).resolves.toEqual({
      disconnected: true
    })
    expect(mockDelete).toHaveBeenCalledWith('/payments/mercadopago/oauth/connection')
  })

  it('getAppointments pide la primera pagina de 50 y desenvuelve results', async () => {
    const results = [{ public_id: 'apt-1' }]
    mockGet.mockResolvedValue({ data: { results, total: 1 } })

    await expect(paymentsService.getAppointments()).resolves.toEqual(results)
    expect(mockGet).toHaveBeenCalledWith('/appointments/search', {
      params: { page: 1, page_size: 50 }
    })
  })

  it('createPreference genera el link del turno por POST sin cuerpo', async () => {
    await paymentsService.createPreference('apt-1')

    expect(mockPost).toHaveBeenCalledWith('/payments/preferences/apt-1')
  })

  it('manualConfirm manda importe y notas del turno', async () => {
    await paymentsService.manualConfirm('apt-1', 1500, 'efectivo')

    expect(mockPost).toHaveBeenCalledWith('/payments/apt-1/manual-confirm', {
      amount: 1500,
      notes: 'efectivo'
    })
  })

  // Saldo restante por turno (D-20261008-01).
  it('recordRemainingPayment manda importe, medio y clave al turno', async () => {
    const resto = { public_id: 'rest-1', amount: '2240.00', remaining_amount: '0.00' }
    mockPost.mockResolvedValue({ data: resto })

    await expect(
      paymentsService.recordRemainingPayment('apt-1', {
        amount: 2240,
        method: 'efectivo',
        idempotencyKey: 'clave-resto-0001'
      })
    ).resolves.toEqual(resto)
    expect(mockPost).toHaveBeenCalledWith('/payments/apt-1/remaining-payment', {
      amount: 2240,
      method: 'efectivo',
      idempotency_key: 'clave-resto-0001'
    })
  })

  it('recordRemainingPayment sin medio lo manda en null', async () => {
    await paymentsService.recordRemainingPayment('apt-1', {
      amount: 100,
      method: null,
      idempotencyKey: 'clave-resto-0002'
    })

    expect(mockPost).toHaveBeenCalledWith('/payments/apt-1/remaining-payment', {
      amount: 100,
      method: null,
      idempotency_key: 'clave-resto-0002'
    })
  })

  it('revertRemainingPayment revierte el resto del turno por POST sin cuerpo', async () => {
    await paymentsService.revertRemainingPayment('apt-1')

    expect(mockPost).toHaveBeenCalledWith('/payments/apt-1/remaining-payment/revert')
  })

  it('refund manda importe, motivo y manual al pago', async () => {
    await paymentsService.refund('pay-1', 500, 'cancelado', true)

    expect(mockPost).toHaveBeenCalledWith('/payments/pay-1/refund', {
      amount: 500,
      reason: 'cancelado',
      manual: true
    })
  })

  it('refund sin argumentos opcionales los deja undefined', async () => {
    await paymentsService.refund('pay-1')

    expect(mockPost).toHaveBeenCalledWith('/payments/pay-1/refund', {
      amount: undefined,
      reason: undefined,
      manual: undefined
    })
  })

  it.each([
    [25, 25],
    [undefined, 100]
  ])('processOutbox(%s) manda limit=%s como param con cuerpo null', async (limit, sent) => {
    await paymentsService.processOutbox(limit)

    expect(mockPost).toHaveBeenCalledWith('/payments/outbox/process', null, {
      params: { limit: sent }
    })
  })
})
