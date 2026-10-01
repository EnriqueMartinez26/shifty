import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { act, renderHook, waitFor } from '@testing-library/react'

import type { SuperAdminStoreRow } from '@application/services/SuperAdminService'

import { useSuperAdminStores } from './useSuperAdmin'

const mockListStores = jest.fn()

jest.mock('@application/services/SuperAdminService', () => ({
  superAdminService: {
    listStores: (...args: unknown[]) => mockListStores(...args)
  }
}))

const envoltorio = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

const tiendas = (desde: number, cantidad: number) =>
  Array.from(
    { length: cantidad },
    (_, i) => ({ public_id: `store-${desde + i}` }) as SuperAdminStoreRow
  )

// 2026-09-30 (FF-24): "Todas" mostraba solo activas, la lista cortaba en 50 y
// cada tecla disparaba hasta 3 requests. El listado pagina de a 50 con el total
// del backend.
describe('useSuperAdminStores', () => {
  beforeEach(() => {
    mockListStores.mockReset()
  })

  it('la segunda pagina pide offset=50', async () => {
    mockListStores
      .mockResolvedValueOnce({ stores: tiendas(0, 50), total: 120 })
      .mockResolvedValueOnce({ stores: tiendas(50, 50), total: 120 })

    const { result } = renderHook(() => useSuperAdminStores({ is_active: 'all' }), {
      wrapper: envoltorio
    })
    await waitFor(() => expect(result.current.hasNextPage).toBe(true))
    // F4-04 a (2026-10-01): la consulta lleva el AbortSignal de react-query.
    expect(mockListStores).toHaveBeenLastCalledWith(
      { is_active: 'all', limit: 50, offset: 0 },
      expect.any(AbortSignal)
    )

    await act(() => result.current.fetchNextPage())

    expect(mockListStores).toHaveBeenLastCalledWith(
      { is_active: 'all', limit: 50, offset: 50 },
      expect.any(AbortSignal)
    )
    await waitFor(() => expect(result.current.data).toHaveLength(100))
    expect(result.current.total).toBe(120)
  })

  it('no hay mas paginas cuando lo cargado llega al total', async () => {
    mockListStores
      .mockResolvedValueOnce({ stores: tiendas(0, 50), total: 70 })
      .mockResolvedValueOnce({ stores: tiendas(50, 20), total: 70 })

    const { result } = renderHook(() => useSuperAdminStores({}), { wrapper: envoltorio })
    await waitFor(() => expect(result.current.hasNextPage).toBe(true))

    await act(() => result.current.fetchNextPage())

    await waitFor(() => expect(result.current.data).toHaveLength(70))
    expect(result.current.hasNextPage).toBe(false)
  })

  it('sin total, una pagina completa sugiere que hay mas y una corta termina', async () => {
    mockListStores
      .mockResolvedValueOnce({ stores: tiendas(0, 50), total: null })
      .mockResolvedValueOnce({ stores: tiendas(50, 3), total: null })

    const { result } = renderHook(() => useSuperAdminStores({}), { wrapper: envoltorio })
    await waitFor(() => expect(result.current.hasNextPage).toBe(true))

    await act(() => result.current.fetchNextPage())

    await waitFor(() => expect(result.current.data).toHaveLength(53))
    expect(result.current.hasNextPage).toBe(false)
    expect(result.current.total).toBeNull()
  })

  it('una tienda repetida entre paginas aparece una sola vez', async () => {
    // El orden es solo created_at: una tienda nueva entre dos paginas corre
    // el offset y la ultima de la primera vuelve a venir en la segunda.
    mockListStores
      .mockResolvedValueOnce({ stores: tiendas(0, 50), total: 51 })
      .mockResolvedValueOnce({ stores: tiendas(49, 2), total: 51 })

    const { result } = renderHook(() => useSuperAdminStores({}), { wrapper: envoltorio })
    await waitFor(() => expect(result.current.hasNextPage).toBe(true))

    await act(() => result.current.fetchNextPage())

    await waitFor(() => expect(result.current.hasNextPage).toBe(false))
    const ids = (result.current.data ?? []).map((store) => store.public_id)
    expect(ids).toHaveLength(51)
    expect(new Set(ids).size).toBe(51)
  })
})
