import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { renderHook, waitFor } from '@testing-library/react'

import { UnauthorizedError, ValidationError } from '@shared/errors'

import { useLogin } from './useLogin'

const mockLogin = jest.fn()
const mockFetchCurrentUser = jest.fn()

jest.mock('@application/services/AuthService', () => ({
  authService: {
    login: (...args: unknown[]) => mockLogin(...args),
    fetchCurrentUser: () => mockFetchCurrentUser()
  }
}))

jest.mock('@infrastructure/http/client', () => ({
  setAuthToken: jest.fn()
}))

jest.mock('../context/AuthContext', () => ({
  useAuth: () => ({ login: jest.fn() })
}))

const envoltorio = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } }
  })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

describe('useLogin', () => {
  beforeEach(() => {
    mockLogin.mockReset()
    mockFetchCurrentUser.mockReset()
  })

  it('una clave mal tipeada no sale como sesion vencida', async () => {
    // F11c-03: el 401 salia como `UnauthorizedError` y el `MutationCache`
    // global de main.tsx lo mandaba al handler que muestra "Sesion expirada"
    // y hace `window.location.href = '/login'`. La recarga borraba el error
    // del formulario: la persona nunca veia por que no entraba.
    mockLogin.mockRejectedValue(new UnauthorizedError('Email o contraseña incorrectos'))

    const { result } = renderHook(() => useLogin(), { wrapper: envoltorio })
    result.current.mutate({ email: 'a@b.com', password: 'mala' })

    await waitFor(() => expect(result.current.isError).toBe(true))
    const error = result.current.error
    expect(error).toBeInstanceOf(ValidationError)
    expect(error).not.toBeInstanceOf(UnauthorizedError)
    expect(error?.message).toBe('Email o contraseña incorrectos')
  })

  it('un error que no es de credenciales sube tal cual', async () => {
    // Contraprueba: solo se traduce el 401 del login. Envolver todo escondería
    // fallas reales de red o del servidor detrás de un cartel de credenciales.
    const caida = new Error('Network Error')
    mockLogin.mockRejectedValue(caida)

    const { result } = renderHook(() => useLogin(), { wrapper: envoltorio })
    result.current.mutate({ email: 'a@b.com', password: 'x' })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error).toBe(caida)
  })

  it('el camino feliz devuelve el token y el usuario', async () => {
    const usuario = {
      public_id: 'usr_1',
      email: 'a@b.com',
      role: 'admin',
      store_id: 'str_1'
    }
    mockLogin.mockResolvedValue({ access_token: 'tok-1' })
    mockFetchCurrentUser.mockResolvedValue(usuario)

    const { result } = renderHook(() => useLogin(), { wrapper: envoltorio })
    result.current.mutate({ email: 'a@b.com', password: 'buena' })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual({ access_token: 'tok-1', user: usuario })
  })

  it('un 401 DESPUES del login si es sesion muerta y no se disfraza', async () => {
    // Marca el limite del try/catch a proposito: solo se traduce el 401 de
    // `authService.login`. Si `/me` rechaza con el token recien emitido, eso
    // NO es una clave mal tipeada, asi que tiene que seguir siendo
    // `UnauthorizedError` y activar el cierre de sesion real. Sin este test,
    // ensanchar el try/catch mostraria "contraseña incorrecta" ante una falla
    // de sesion y nadie se enteraria.
    mockLogin.mockResolvedValue({ access_token: 'tok-1' })
    mockFetchCurrentUser.mockRejectedValue(new UnauthorizedError('Sesion invalida'))

    const { result } = renderHook(() => useLogin(), { wrapper: envoltorio })
    result.current.mutate({ email: 'a@b.com', password: 'buena' })

    await waitFor(() => expect(result.current.isError).toBe(true))
    expect(result.current.error).toBeInstanceOf(UnauthorizedError)
    expect(result.current.error).not.toBeInstanceOf(ValidationError)
  })
})
