import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { act, renderHook, waitFor } from '@testing-library/react'

import { useCreateManagedService, useManagedServices } from './useManagedServices'

const mockListServices = jest.fn()
const mockCreateService = jest.fn()

jest.mock('@application/services/ServiceService', () => ({
  serviceService: {
    listServices: () => mockListServices(),
    createService: (...args: unknown[]) => mockCreateService(...args)
  }
}))

const envoltorio = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } }
  })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

describe('useManagedServices', () => {
  it('dar de alta un servicio refresca la lista que leen el alta de profesionales y los links', async () => {
    // F11c-10: StaffFormModal y ShareLinksPanel leian `['services']` con una
    // copia literal de este hook. Ahora usan este mismo, asi que la
    // invalidacion de las mutaciones de al lado es la que los mantiene al dia.
    mockListServices.mockResolvedValue([])
    mockCreateService.mockResolvedValue({ id: 'svc_1' })

    const { result } = renderHook(
      () => ({ lista: useManagedServices(), alta: useCreateManagedService() }),
      { wrapper: envoltorio }
    )
    await waitFor(() => expect(result.current.lista.isSuccess).toBe(true))
    expect(mockListServices).toHaveBeenCalledTimes(1)

    await act(() =>
      result.current.alta.mutateAsync({ name: 'Corte' } as Parameters<
        typeof result.current.alta.mutateAsync
      >[0])
    )

    await waitFor(() => expect(mockListServices).toHaveBeenCalledTimes(2))
  })
})
