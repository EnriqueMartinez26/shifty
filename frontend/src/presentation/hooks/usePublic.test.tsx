import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { act, renderHook, waitFor } from '@testing-library/react'

import { ConflictError } from '@shared/errors'

import { useCreatePublicBooking, usePublicDepositPreview } from './usePublic'

const mockCreateBooking = jest.fn()
const mockPreviewDeposit = jest.fn()

jest.mock('@application/services/PublicBookingService', () => ({
  publicBookingService: {
    createBooking: (...args: unknown[]) => mockCreateBooking(...args),
    previewDeposit: (...args: unknown[]) => mockPreviewDeposit(...args)
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
