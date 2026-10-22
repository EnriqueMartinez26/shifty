import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { act, renderHook, waitFor } from '@testing-library/react'

import { useBulkCancelPortalBookings, useRecentPortalBookings } from './usePortalBookings'

const mockListRecent = jest.fn()
const mockBulkCancel = jest.fn()

jest.mock('@application/services/PortalBookingsService', () => ({
  portalBookingsService: {
    listRecent: (...args: unknown[]) => mockListRecent(...args),
    bulkCancel: (...args: unknown[]) => mockBulkCancel(...args)
  }
}))

const conCliente = () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const invalidar = jest.spyOn(queryClient, 'invalidateQueries')
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  return { invalidar, wrapper }
}

describe('useRecentPortalBookings', () => {
  beforeEach(() => {
    mockListRecent.mockReset()
  })

  it('pide la ventana elegida', async () => {
    mockListRecent.mockResolvedValue([{ public_id: 'apt-1' }])
    const { wrapper } = conCliente()

    const { result } = renderHook(() => useRecentPortalBookings(168, true), { wrapper })

    await waitFor(() => expect(result.current.data).toEqual([{ public_id: 'apt-1' }]))
    expect(mockListRecent).toHaveBeenCalledWith(168)
  })

  it('no pide nada si quien mira no gestiona la tienda', () => {
    const { wrapper } = conCliente()

    renderHook(() => useRecentPortalBookings(72, false), { wrapper })

    expect(mockListRecent).not.toHaveBeenCalled()
  })
})

describe('useBulkCancelPortalBookings', () => {
  it('cancela y vuelve a pedir la lista, la agenda y el resumen', async () => {
    mockBulkCancel.mockResolvedValue({ cancelled: ['apt-1'], skipped: [] })
    const { invalidar, wrapper } = conCliente()
    const { result } = renderHook(() => useBulkCancelPortalBookings(), { wrapper })

    await act(async () => {
      await result.current.mutateAsync({ ids: ['apt-1'], reason: 'Bot' })
    })

    expect(mockBulkCancel).toHaveBeenCalledWith(['apt-1'], 'Bot')
    expect(invalidar).toHaveBeenCalledWith({ queryKey: ['portal-bookings'] })
    expect(invalidar).toHaveBeenCalledWith({ queryKey: ['calendar-agenda'] })
    expect(invalidar).toHaveBeenCalledWith({ queryKey: ['dashboard-summary'] })
  })
})
