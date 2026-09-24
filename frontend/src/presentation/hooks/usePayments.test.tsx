import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { renderHook, waitFor } from '@testing-library/react'

import { useManualConfirmPayment, useRefundPayment } from './usePayments'

const mockManualConfirm = jest.fn()
const mockRefund = jest.fn()

jest.mock('@application/services/PaymentsService', () => ({
  paymentsService: {
    manualConfirm: (...args: unknown[]) => mockManualConfirm(...args),
    refund: (...args: unknown[]) => mockRefund(...args)
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
