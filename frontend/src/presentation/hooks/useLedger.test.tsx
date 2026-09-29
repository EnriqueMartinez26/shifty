import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { act, renderHook, waitFor } from '@testing-library/react'

import { useCustomerLedger } from './useLedger'
import { useReportSummary } from './useReports'

const mockGetCustomerLedger = jest.fn()
const mockGetSummary = jest.fn()

jest.mock('@application/services/LedgerService', () => ({
  ledgerService: {
    getCustomerLedger: (...args: unknown[]) => mockGetCustomerLedger(...args)
  }
}))

jest.mock('@application/services/ReportsService', () => ({
  reportsService: { getSummary: (...args: unknown[]) => mockGetSummary(...args) }
}))

const envoltorio = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

const pagina = (id: string, nextCursor: string | null) => ({
  client_id: 'cli-a',
  balance: 500,
  total: 2,
  movements: [{ public_id: id }],
  next_cursor: nextCursor
})

describe('useCustomerLedger', () => {
  it('pagina con el cursor del backend y deja de ofrecer mas sin next_cursor (FF-20)', async () => {
    mockGetCustomerLedger
      .mockResolvedValueOnce(pagina('mov-2', 'cur-1'))
      .mockResolvedValueOnce(pagina('mov-1', null))

    const { result } = renderHook(() => useCustomerLedger('cli-a'), { wrapper: envoltorio })
    await waitFor(() => expect(result.current.hasNextPage).toBe(true))
    expect(mockGetCustomerLedger).toHaveBeenLastCalledWith('cli-a', undefined)

    await act(async () => {
      await result.current.fetchNextPage()
    })

    expect(mockGetCustomerLedger).toHaveBeenLastCalledWith('cli-a', 'cur-1')
    await waitFor(() => expect(result.current.hasNextPage).toBe(false))
    // Mas nuevo primero, sin invertir: la segunda pagina va detras.
    expect(result.current.movements.map((m) => m.public_id)).toEqual(['mov-2', 'mov-1'])
    expect(result.current.total).toBe(2)
  })
})

// Vive aca porque este archivo ya prueba hooks reales con QueryClient.
describe('useReportSummary', () => {
  it('conserva la pagina anterior solo dentro del mismo rango (R4-001)', async () => {
    mockGetSummary.mockResolvedValueOnce({ id: 'pagina-1' }).mockReturnValue(new Promise(() => {}))
    const { result, rerender } = renderHook(
      ({ from, offset }) => useReportSummary(from, '2026-09-30', true, { limit: 100, offset }),
      { wrapper: envoltorio, initialProps: { from: '2026-09-01', offset: 0 } }
    )
    await waitFor(() => expect(result.current.data).toEqual({ id: 'pagina-1' }))

    rerender({ from: '2026-09-01', offset: 100 })
    expect(result.current.isPlaceholderData).toBe(true)

    rerender({ from: '2026-08-01', offset: 0 })
    await waitFor(() => expect(result.current.isLoading).toBe(true))
    expect(result.current.data).toBeUndefined()
  })
})
