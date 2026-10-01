import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { act, renderHook, waitFor } from '@testing-library/react'

import { ConflictError, RateLimitError } from '@shared/errors'

import {
  useCreatePublicBooking,
  usePublicDepositPreview,
  usePublicPaymentStatus,
  useRescheduleClientAppointment
} from './usePublic'
import { PAYMENT_POLL_MAX_MS } from '../lib/paymentPolling'

const mockCreateBooking = jest.fn()
const mockPreviewDeposit = jest.fn()
const mockGetPaymentStatus = jest.fn()
const mockReschedule = jest.fn()

jest.mock('@application/services/PublicBookingService', () => ({
  publicBookingService: {
    createBooking: (...args: unknown[]) => mockCreateBooking(...args),
    previewDeposit: (...args: unknown[]) => mockPreviewDeposit(...args),
    getPaymentStatus: (...args: unknown[]) => mockGetPaymentStatus(...args),
    rescheduleClientAppointment: (...args: unknown[]) => mockReschedule(...args)
  }
}))

const nuevoCliente = () =>
  new QueryClient({ defaultOptions: { mutations: { retry: false }, queries: { retry: false } } })

const envoltorio = (queryClient: QueryClient) => {
  const Envoltorio = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  return Envoltorio
}

describe('useCreatePublicBooking', () => {
  const claveDelPaso2 = ['public-availability', 's', 'svc', '2026-09-25', false]

  // Mientras se confirma, el paso 2 del wizard esta desmontado: su consulta de
  // disponibilidad queda inactiva y solo `refetchType: 'all'` la vuelve a pedir.
  const clienteConGrillaDelPaso2 = () => {
    const queryClient = nuevoCliente()
    const refetchGrilla = jest.fn().mockResolvedValue([])
    queryClient.setQueryDefaults(['public-availability'], { queryFn: refetchGrilla })
    queryClient.setQueryData(claveDelPaso2, [{ start_time: '10:00' }])
    return { queryClient, refetchGrilla }
  }

  beforeEach(() => mockCreateBooking.mockReset())

  it('un 409 por horario tomado vuelve a pedir la grilla inactiva del paso 2 (FF-33)', async () => {
    // FF-33 (2026-09-30): tras un 409 por horario ocupado, al volver al paso 2
    // la grilla seguia mostrando libre ese horario: la invalidacion solo
    // refrescaba consultas activas y la del paso 2 esta desmontada.
    mockCreateBooking.mockRejectedValue(
      new ConflictError('Horario ocupado', { errorCode: 'SLOT_TAKEN', statusCode: 409 })
    )
    const { queryClient, refetchGrilla } = clienteConGrillaDelPaso2()
    const invalidate = jest.spyOn(queryClient, 'invalidateQueries')

    const { result } = renderHook(() => useCreatePublicBooking(), {
      wrapper: envoltorio(queryClient)
    })
    await act(async () => {
      await expect(
        result.current.mutateAsync({} as Parameters<typeof result.current.mutateAsync>[0])
      ).rejects.toThrow('Horario ocupado')
    })

    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ['public-availability'],
      refetchType: 'all'
    })
    await waitFor(() => expect(refetchGrilla).toHaveBeenCalledTimes(1))
  })

  it('una reserva exitosa tambien vuelve a pedir la grilla (FF-33)', async () => {
    // FF-33 (2026-09-30): con la reserva hecha, "Hacer otra reserva" podia
    // mostrar libre el horario recien tomado durante los 30 s de staleTime.
    mockCreateBooking.mockResolvedValue({ public_id: 'appt-1' })
    const { queryClient, refetchGrilla } = clienteConGrillaDelPaso2()
    const invalidate = jest.spyOn(queryClient, 'invalidateQueries')

    const { result } = renderHook(() => useCreatePublicBooking(), {
      wrapper: envoltorio(queryClient)
    })
    await act(() =>
      result.current.mutateAsync({} as Parameters<typeof result.current.mutateAsync>[0])
    )

    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ['public-availability'],
      refetchType: 'all'
    })
    await waitFor(() => expect(refetchGrilla).toHaveBeenCalledTimes(1))
  })
})

describe('useRescheduleClientAppointment', () => {
  it('un 409 vuelve a pedir la grilla para que el horario tomado deje de ofrecerse (FF-06)', async () => {
    // FF-06 (2026-10-01): tras un 409 por horario tomado la grilla de "Mis
    // turnos" seguia mostrando libre ese horario durante los 30 s de
    // staleTime: solo se invalidaba al tener exito.
    mockReschedule.mockRejectedValue(
      new ConflictError('Horario ocupado', { errorCode: 'APPOINTMENT_CONFLICT', statusCode: 409 })
    )
    const queryClient = nuevoCliente()
    const invalidate = jest.spyOn(queryClient, 'invalidateQueries')

    const { result } = renderHook(() => useRescheduleClientAppointment(), {
      wrapper: envoltorio(queryClient)
    })
    await act(async () => {
      await expect(
        result.current.mutateAsync({
          publicId: 'appt-1',
          phone: '1155550101',
          newStartsAt: '2026-09-16T19:00:00+00:00',
          idempotencyKey: 'k-1'
        })
      ).rejects.toThrow('Horario ocupado')
    })

    expect(invalidate).toHaveBeenCalledWith({
      queryKey: ['public-availability'],
      refetchType: 'all'
    })
  })
})

describe('usePublicDepositPreview', () => {
  const turno = { storePublicId: 'store-1', serviceId: 'svc-1' }

  beforeEach(() => mockPreviewDeposit.mockReset())

  it('al completar el telefono conserva la seña anterior mientras carga (FF-32)', async () => {
    // FF-32 (2026-09-29): al pasar el telefono de 5 a 6 digitos cambiaba la
    // clave, la seña quedaba vacia mientras cargaba y el boton de Mercado Pago
    // parpadeaba.
    let resolverConTelefono: (value: unknown) => void = () => undefined
    mockPreviewDeposit.mockImplementation(({ clientPhone }: { clientPhone?: string }) =>
      clientPhone
        ? new Promise((resolve) => {
            resolverConTelefono = resolve
          })
        : Promise.resolve({ amount: 1000 })
    )
    const { result, rerender } = renderHook(
      (props: { clientPhone?: string }) =>
        usePublicDepositPreview({ ...turno, startsAt: '2026-10-01T12:00:00Z', ...props }),
      { wrapper: envoltorio(nuevoCliente()), initialProps: {} }
    )
    await waitFor(() => expect(result.current.data).toEqual({ amount: 1000 }))

    rerender({ clientPhone: '115555' })

    expect(result.current.data).toEqual({ amount: 1000 })
    expect(result.current.isPlaceholderData).toBe(true)
    await act(async () => {
      resolverConTelefono({ amount: 1500 })
      await Promise.resolve()
    })
    await waitFor(() => expect(result.current.data).toEqual({ amount: 1500 }))
  })

  it('con otro horario no muestra la seña del turno anterior', async () => {
    mockPreviewDeposit.mockImplementation(({ startsAt }: { startsAt: string }) =>
      startsAt === '2026-10-01T12:00:00Z'
        ? Promise.resolve({ amount: 1000 })
        : new Promise(() => undefined)
    )
    const { result, rerender } = renderHook(
      (props: { startsAt: string }) => usePublicDepositPreview({ ...turno, ...props }),
      {
        wrapper: envoltorio(nuevoCliente()),
        initialProps: { startsAt: '2026-10-01T12:00:00Z' }
      }
    )
    await waitFor(() => expect(result.current.data).toEqual({ amount: 1000 }))

    rerender({ startsAt: '2026-10-02T12:00:00Z' })

    expect(result.current.data).toBeUndefined()
  })
})

describe('usePublicPaymentStatus', () => {
  const pendiente = { payment_status: 'pending', appointment_status: 'pending_payment' }

  beforeEach(() => {
    mockGetPaymentStatus.mockReset()
    jest.useFakeTimers()
  })

  afterEach(() => jest.useRealTimers())

  const avanzar = (ms: number) => act(() => jest.advanceTimersByTimeAsync(ms))

  it('baja el ritmo y deja de sondear a los 30 minutos, avisando que corto (F4-05)', async () => {
    // F4-05 (2026-09-30): sondeo fijo de 2 s sin corte, unas 900 requests en
    // 30 min por cada cliente que volvia de Mercado Pago con el pago pendiente.
    mockGetPaymentStatus.mockResolvedValue(pendiente)
    const { result } = renderHook(() => usePublicPaymentStatus('store-1', 'pay-1'), {
      wrapper: envoltorio(nuevoCliente())
    })

    await avanzar(30_000)
    // Cada 2 s el primer medio minuto: 0, 2, ..., 30 s.
    expect(mockGetPaymentStatus).toHaveBeenCalledTimes(16)
    expect(result.current.pollingStopped).toBe(false)

    await avanzar(PAYMENT_POLL_MAX_MS - 30_000 - 1)
    expect(mockGetPaymentStatus).toHaveBeenCalledTimes(145)
    expect(result.current.pollingStopped).toBe(false)

    // La ultima consulta sale justo en el corte y su respuesta vuelve a
    // renderizar: sin eso la pantalla seguia diciendo "no cierres esta
    // pantalla" aunque nadie consultaba mas.
    await avanzar(1)
    await waitFor(() => expect(result.current.pollingStopped).toBe(true))
    // 16 a 2 s, 18 a 5 s hasta los 2 min y 112 a 15 s hasta los 30 min.
    expect(mockGetPaymentStatus).toHaveBeenCalledTimes(146)

    await avanzar(10 * 60_000)
    expect(mockGetPaymentStatus).toHaveBeenCalledTimes(146)
    expect(result.current.pollingStopped).toBe(true)
    // Recorrer 30 min de reloj falso con 146 consultas lleva unos 4 s reales.
  }, 20_000)

  it('un pago aprobado deja de sondear sin marcar el corte', async () => {
    mockGetPaymentStatus
      .mockResolvedValueOnce(pendiente)
      .mockResolvedValue({ payment_status: 'approved', appointment_status: 'confirmed' })
    const { result } = renderHook(() => usePublicPaymentStatus('store-1', 'pay-1'), {
      wrapper: envoltorio(nuevoCliente())
    })

    await avanzar(PAYMENT_POLL_MAX_MS + 60_000)

    expect(mockGetPaymentStatus).toHaveBeenCalledTimes(2)
    expect(result.current.data?.payment_status).toBe('approved')
    expect(result.current.pollingStopped).toBe(false)
  })

  it('no pisa la politica global de reintentos: un 429 no se repite (F4-05)', async () => {
    // F4-05 (2026-09-30): el `retry: 2` propio reintentaba tambien los 429 y
    // sumaba carga justo cuando el servidor pedia esperar.
    mockGetPaymentStatus.mockRejectedValue(
      new RateLimitError('Demasiadas consultas', { statusCode: 429, retryAfter: 20 })
    )
    const { result } = renderHook(() => usePublicPaymentStatus('store-1', 'pay-1'), {
      wrapper: envoltorio(nuevoCliente())
    })

    await avanzar(10_000)

    expect(mockGetPaymentStatus).toHaveBeenCalledTimes(1)
    expect(result.current.isError).toBe(true)
  })
})
