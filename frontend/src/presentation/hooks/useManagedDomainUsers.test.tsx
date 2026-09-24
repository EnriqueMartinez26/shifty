import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { act, renderHook, waitFor } from '@testing-library/react'

import { useCreateManagedDomainUser, useStoreClients } from './useManagedDomainUsers'

const mockListClients = jest.fn()
const mockCreateUser = jest.fn()

jest.mock('@application/services/UserService', () => ({
  userService: {
    listClients: () => mockListClients(),
    createUser: (...args: unknown[]) => mockCreateUser(...args)
  }
}))

const envoltorio = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } }
  })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

describe('useStoreClients', () => {
  it('dar de alta un usuario refresca los clientes que lee Cuentas pendientes (F11c-07)', async () => {
    // Antes Ledger leia ['users', ...] con otra stack y el alta invalidaba
    // ['managed-users']: el cliente nuevo no aparecia hasta recargar.
    mockListClients.mockResolvedValue([])
    mockCreateUser.mockResolvedValue({ id: 'usr_1' })

    const { result } = renderHook(
      () => ({ clientes: useStoreClients(), alta: useCreateManagedDomainUser() }),
      { wrapper: envoltorio }
    )
    await waitFor(() => expect(result.current.clientes.isSuccess).toBe(true))
    expect(mockListClients).toHaveBeenCalledTimes(1)

    await act(() =>
      result.current.alta.mutateAsync({ email: 'ana@example.com' } as Parameters<
        typeof result.current.alta.mutateAsync
      >[0])
    )

    await waitFor(() => expect(mockListClients).toHaveBeenCalledTimes(2))
  })
})
