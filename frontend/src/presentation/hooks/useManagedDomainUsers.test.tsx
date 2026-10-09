import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { act, renderHook, waitFor } from '@testing-library/react'

import { User } from '@domain/entities/User'
import type { UserListQuery } from '@domain/repositories/IUserRepository'

import { useCreateManagedDomainUser, useManagedDomainUsers } from './useManagedDomainUsers'

const mockListUsers = jest.fn()
const mockCreateUser = jest.fn()

jest.mock('@application/services/UserService', () => ({
  userService: {
    listUsers: (...args: unknown[]) => mockListUsers(...args),
    createUser: (...args: unknown[]) => mockCreateUser(...args)
  }
}))

const envoltorio = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } }
  })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

const usuario = (n: number) =>
  User.fromPrimitives({
    id: `usr-${n}`,
    email: `u${n}@example.com`,
    firstName: `U${n}`,
    lastName: null,
    phone: null,
    role: 'staff',
    isActive: true,
    createdAt: '2026-09-01T12:00:00+00:00'
  })

const pagina = (desde: number, cantidad: number) =>
  Array.from({ length: cantidad }, (_, i) => usuario(desde + i))

const consulta: UserListQuery = { limit: 100, includeInactive: true }

// 2026-09-30 (F4-03): la lista de usuarios cortaba en 200 sin forma de ver el
// resto. El hook ahora pagina con offset y el contenedor muestra "Ver mas".
describe('useManagedDomainUsers', () => {
  beforeEach(() => {
    mockListUsers.mockReset()
    mockCreateUser.mockReset()
  })

  it('una pagina llena habilita la siguiente, que pide offset=100', async () => {
    mockListUsers.mockImplementation((q: UserListQuery) =>
      Promise.resolve(q.offset === 0 ? pagina(0, 100) : pagina(100, 3))
    )

    const { result } = renderHook(() => useManagedDomainUsers(consulta), { wrapper: envoltorio })
    await waitFor(() => expect(result.current.data).toHaveLength(100))
    // 2026-10-02: la senal de react-query viaja hasta el servicio para que una
    // busqueda reemplazada cancele su request.
    expect(mockListUsers).toHaveBeenLastCalledWith(
      { ...consulta, offset: 0 },
      expect.any(AbortSignal)
    )
    expect(result.current.hasNextPage).toBe(true)

    await act(() => result.current.fetchNextPage())

    expect(mockListUsers).toHaveBeenLastCalledWith(
      { ...consulta, offset: 100 },
      expect.any(AbortSignal)
    )
    await waitFor(() => expect(result.current.data).toHaveLength(103))
    // La segunda pagina vino corta: no hay mas que pedir.
    expect(result.current.hasNextPage).toBe(false)
  })

  it('una pagina corta no ofrece "Ver mas"', async () => {
    mockListUsers.mockResolvedValue(pagina(0, 5))

    const { result } = renderHook(() => useManagedDomainUsers(consulta), { wrapper: envoltorio })
    await waitFor(() => expect(result.current.data).toHaveLength(5))

    expect(result.current.hasNextPage).toBe(false)
  })

  it('una fila repetida entre paginas aparece una sola vez', async () => {
    // El backend ordena solo por created_at: con empates el offset puede
    // devolver en la pagina 2 una fila que ya vino en la 1.
    mockListUsers.mockImplementation((q: UserListQuery) =>
      Promise.resolve(q.offset === 0 ? pagina(0, 100) : [usuario(99), usuario(100)])
    )

    const { result } = renderHook(() => useManagedDomainUsers(consulta), { wrapper: envoltorio })
    await waitFor(() => expect(result.current.data).toHaveLength(100))
    await act(() => result.current.fetchNextPage())

    await waitFor(() => expect(result.current.data).toHaveLength(101))
    const ids = result.current.data?.map((u) => u.id) ?? []
    expect(ids.filter((id) => id === 'usr-99')).toHaveLength(1)
    expect(ids.at(-1)).toBe('usr-100')
  })

  it('dar de alta un usuario vuelve a pedir todas las paginas cargadas', async () => {
    mockListUsers.mockImplementation((q: UserListQuery) =>
      Promise.resolve(q.offset === 0 ? pagina(0, 100) : pagina(100, 3))
    )
    mockCreateUser.mockResolvedValue(usuario(500))

    const { result } = renderHook(
      () => ({ lista: useManagedDomainUsers(consulta), alta: useCreateManagedDomainUser() }),
      { wrapper: envoltorio }
    )
    await waitFor(() => expect(result.current.lista.data).toHaveLength(100))
    await act(() => result.current.lista.fetchNextPage())
    await waitFor(() => expect(result.current.lista.data).toHaveLength(103))
    mockListUsers.mockClear()

    await act(() =>
      result.current.alta.mutateAsync({ email: 'ana@example.com' } as Parameters<
        typeof result.current.alta.mutateAsync
      >[0])
    )

    await waitFor(() => expect(mockListUsers).toHaveBeenCalledTimes(2))
    expect(mockListUsers.mock.calls.map(([q]: [UserListQuery]) => q.offset)).toEqual([0, 100])
  })
})
