import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { act, renderHook, waitFor } from '@testing-library/react'

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
  beforeEach(() => mockCreateBooking.mockReset())

  it('una reserva fallida invalida la disponibilidad publica (FF-33)', async () => {
    // FF-33 (2026-09-29): tras un 409 por horario ocupado, al volver al paso 2
    // la grilla seguia mostrando libre ese horario por el staleTime de 30 s.
    mockCreateBooking.mockRejectedValue(new Error('Horario ocupado'))
    const queryClient = nuevoCliente()
    const invalidate = jest.spyOn(queryClient, 'invalidateQueries')

    const { result } = renderHook(() => useCreatePublicBooking(), {
      wrapper: envoltorio(queryClient)
    })
    await act(async () => {
      await expect(
        result.current.mutateAsync({} as Parameters<typeof result.current.mutateAsync>[0])
      ).rejects.toThrow('Horario ocupado')
    })

    expect(invalidate).toHaveBeenCalledWith({ queryKey: ['public-availability'] })
  })

  it('una reserva exitosa no invalida la disponibilidad', async () => {
    mockCreateBooking.mockResolvedValue({ public_id: 'appt-1' })
    const queryClient = nuevoCliente()
    const invalidate = jest.spyOn(queryClient, 'invalidateQueries')

    const { result } = renderHook(() => useCreatePublicBooking(), {
      wrapper: envoltorio(queryClient)
    })
    await act(() =>
      result.current.mutateAsync({} as Parameters<typeof result.current.mutateAsync>[0])
    )

    expect(invalidate).not.toHaveBeenCalled()
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
