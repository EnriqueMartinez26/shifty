import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { renderHook, waitFor } from '@testing-library/react'

import {
  useCreatePaymentPreference,
  useManualConfirmPayment,
  useRecordRemainingPayment,
  useRefundPayment,
  useRevertRemainingPayment
} from './usePayments'

const mockManualConfirm = jest.fn()
const mockRefund = jest.fn()
const mockCreatePreference = jest.fn()
const mockRecordRemaining = jest.fn()
const mockRevertRemaining = jest.fn()

jest.mock('@application/services/PaymentsService', () => ({
  paymentsService: {
    manualConfirm: (...args: unknown[]) => mockManualConfirm(...args),
    refund: (...args: unknown[]) => mockRefund(...args),
    createPreference: (...args: unknown[]) => mockCreatePreference(...args),
    recordRemainingPayment: (...args: unknown[]) => mockRecordRemaining(...args),
    revertRemainingPayment: (...args: unknown[]) => mockRevertRemaining(...args)
  }
}))

const crearEnvoltorio = () => {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } }
  })
  const invalidateSpy = jest.spyOn(queryClient, 'invalidateQueries')
  const envoltorio = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  return { envoltorio, invalidateSpy }
}

const clavesInvalidadas = (spy: jest.SpyInstance) =>
  spy.mock.calls.map(([filters]) => (filters as { queryKey: unknown[] }).queryKey)

// F11c-09: confirmar a mano o devolver no invalidaba nada y los tableros de
// Cobros quedaban mostrando el estado anterior hasta que venciera el cache.
const CLAVES_DEL_COBRO = [
  ['payments-reconciliation-summary'],
  ['payments-appointments'],
  ['payments-outbox-stats'],
  ['calendar-agenda']
]

describe('usePayments: mutaciones que cambian el estado del cobro', () => {
  beforeEach(() => {
    mockManualConfirm.mockReset()
    mockRefund.mockReset()
    mockCreatePreference.mockReset()
  })

  // Revision de la PR #131 (S3, 2026-10-08): despues de "Crear link" la
  // tarjeta seguia diciendo que el turno no tenia cobro, porque la lista de
  // Cobros no se refrescaba. El link crea (o reabre) el cobro del turno y
  // suma un pago pendiente al resumen.
  it('crear un link refresca los turnos de Cobros y el resumen', async () => {
    mockCreatePreference.mockResolvedValue({ appointment_id: 'apt_1' })
    const { envoltorio, invalidateSpy } = crearEnvoltorio()

    const { result } = renderHook(() => useCreatePaymentPreference(), { wrapper: envoltorio })
    result.current.mutate('apt_1')

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(clavesInvalidadas(invalidateSpy)).toEqual([
      ['payments-reconciliation-summary'],
      ['payments-appointments']
    ])
  })

  it('un link que falla no invalida nada', async () => {
    mockCreatePreference.mockRejectedValue(new Error('Mercado Pago no respondio'))
    const { envoltorio, invalidateSpy } = crearEnvoltorio()

    const { result } = renderHook(() => useCreatePaymentPreference(), { wrapper: envoltorio })
    result.current.mutate('apt_1')

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(invalidateSpy).not.toHaveBeenCalled()
  })

  it('confirmar un pago a mano refresca el resumen, los turnos, el outbox y la agenda', async () => {
    mockManualConfirm.mockResolvedValue({ public_id: 'pay_1' })
    const { envoltorio, invalidateSpy } = crearEnvoltorio()

    const { result } = renderHook(() => useManualConfirmPayment(), { wrapper: envoltorio })
    result.current.mutate({ appointmentId: 'apt_1' })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(clavesInvalidadas(invalidateSpy)).toEqual(CLAVES_DEL_COBRO)
  })

  it('registrar una devolucion refresca las mismas consultas', async () => {
    mockRefund.mockResolvedValue({ public_id: 'pay_1' })
    const { envoltorio, invalidateSpy } = crearEnvoltorio()

    const { result } = renderHook(() => useRefundPayment(), { wrapper: envoltorio })
    result.current.mutate({ paymentId: 'pay_1', manual: true })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(clavesInvalidadas(invalidateSpy)).toEqual(CLAVES_DEL_COBRO)
  })

  it('una devolucion rechazada no invalida nada', async () => {
    mockRefund.mockRejectedValue(new Error('Solo se pueden reembolsar pagos acreditados'))
    const { envoltorio, invalidateSpy } = crearEnvoltorio()

    const { result } = renderHook(() => useRefundPayment(), { wrapper: envoltorio })
    result.current.mutate({ paymentId: 'pay_1' })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(invalidateSpy).not.toHaveBeenCalled()
  })
})

// Saldo restante por turno (D-20261008-01): el resto cambia lo pagado del
// turno en Cobros y el ingreso de reportes, panel y conciliacion.
describe('usePayments: el resto del turno', () => {
  const CLAVES_DEL_RESTO = [
    ['payments-reconciliation-summary'],
    ['payments-appointments'],
    ['reports-summary'],
    ['reports-professionals'],
    ['dashboard-summary']
  ]

  beforeEach(() => {
    mockRecordRemaining.mockReset()
    mockRevertRemaining.mockReset()
  })

  it('registrar el resto llama al servicio y refresca Cobros, reportes y panel', async () => {
    mockRecordRemaining.mockResolvedValue({ public_id: 'rest-1' })
    const { envoltorio, invalidateSpy } = crearEnvoltorio()

    const { result } = renderHook(() => useRecordRemainingPayment(), { wrapper: envoltorio })
    result.current.mutate({
      appointmentId: 'apt_1',
      amount: 2240,
      method: 'efectivo',
      idempotencyKey: 'clave-resto-0001'
    })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mockRecordRemaining).toHaveBeenCalledWith('apt_1', {
      amount: 2240,
      method: 'efectivo',
      idempotencyKey: 'clave-resto-0001'
    })
    expect(clavesInvalidadas(invalidateSpy)).toEqual(CLAVES_DEL_RESTO)
  })

  it('revertir el resto refresca lo mismo', async () => {
    mockRevertRemaining.mockResolvedValue({ public_id: 'rest-1' })
    const { envoltorio, invalidateSpy } = crearEnvoltorio()

    const { result } = renderHook(() => useRevertRemainingPayment(), { wrapper: envoltorio })
    result.current.mutate('apt_1')

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(mockRevertRemaining).toHaveBeenCalledWith('apt_1')
    expect(clavesInvalidadas(invalidateSpy)).toEqual(CLAVES_DEL_RESTO)
  })

  it('un registro que falla no invalida nada', async () => {
    mockRecordRemaining.mockRejectedValue(new Error('409'))
    const { envoltorio, invalidateSpy } = crearEnvoltorio()

    const { result } = renderHook(() => useRecordRemainingPayment(), { wrapper: envoltorio })
    result.current.mutate({
      appointmentId: 'apt_1',
      amount: 1,
      method: null,
      idempotencyKey: 'clave-resto-0002'
    })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(invalidateSpy).not.toHaveBeenCalled()
  })
})
