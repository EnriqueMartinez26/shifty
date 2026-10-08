import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { act, renderHook, waitFor } from '@testing-library/react'

import { useAddMyselfAsStaff, useManagedStaff } from './useManagedStaff'

const mockListStaff = jest.fn()
const mockAddMyself = jest.fn()

jest.mock('@application/services/StaffService', () => ({
  staffService: {
    listStaff: () => mockListStaff(),
    addMyself: (...args: unknown[]) => mockAddMyself(...args)
  }
}))

// useManagedStaff tambien exporta el hook de la semana (#130), que importa el
// cliente HTTP real (import.meta, que ts-jest no compila).
jest.mock('@application/services/StaffSchedulesService', () => ({
  staffSchedulesService: {}
}))

const envoltorio = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } }
  })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

// 2026-10-08, decision de Mateo: al agregarse, el dueno tiene que aparecer en
// la lista del personal (y el boton "Agregarme" desaparecer).
describe('useAddMyselfAsStaff', () => {
  it('agrega la cuenta y refresca la lista del personal', async () => {
    mockListStaff.mockResolvedValue([])
    mockAddMyself.mockResolvedValue({ id: 'usr-duenio' })

    const { result } = renderHook(
      () => ({ lista: useManagedStaff(), agregarme: useAddMyselfAsStaff() }),
      { wrapper: envoltorio }
    )
    await waitFor(() => expect(result.current.lista.isSuccess).toBe(true))

    await act(() =>
      result.current.agregarme.mutateAsync({ displayName: 'Enrique', serviceIds: ['svc-1'] })
    )

    expect(mockAddMyself).toHaveBeenCalledWith({ displayName: 'Enrique', serviceIds: ['svc-1'] })
    await waitFor(() => expect(mockListStaff).toHaveBeenCalledTimes(2))
  })
})
