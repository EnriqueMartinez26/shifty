import { StrictMode } from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { setAuthToken, SESSION_EXPIRED_EVENT } from '@infrastructure/http/client'
import { PEER_LOGOUT_EVENT, PEER_SESSION_EVENT } from '@infrastructure/http/sessionSync'

import { AuthProvider, useAuth } from './AuthContext'

/**
 * 2026-09-28 (F4-01, F4-02, FF-26). Sintomas:
 * - con StrictMode el montaje mandaba dos POST /auth/refresh y el backend
 *   tomaba el segundo como reuso (logout en todos los dispositivos);
 * - ni el logout ni el vencimiento limpiaban el cache de react-query: el
 *   usuario siguiente veia datos del anterior. Lo borraba de rebote la
 *   recarga a /login del UnauthorizedErrorHandler, que ya no existe;
 * - un 503 o un corte de red al montar mandaba a /login.
 * Se usa el cliente HTTP real (sessionSync incluido) con axios falso.
 */

const mockPost = jest.fn()
const mockGet = jest.fn()

jest.mock('axios', () => ({
  __esModule: true,
  default: {
    create: () => ({
      post: (...args: unknown[]) => mockPost(...args),
      get: (...args: unknown[]) => mockGet(...args),
      request: jest.fn(),
      interceptors: { request: { use: jest.fn() }, response: { use: jest.fn() } }
    })
  }
}))

jest.mock('@infrastructure/http/runtime-env', () => ({
  __esModule: true,
  getRuntimeEnv: () => ({ apiUrl: 'http://test-api', dev: true })
}))

const usuarioA = { email: 'a@x.com', role: 'store_admin', store_id: 's1', public_id: 'usr-a' }
const usuarioB = { email: 'b@x.com', role: 'professional', store_id: 's1', public_id: 'usr-b' }

const refreshCalls = () => mockPost.mock.calls.filter(([url]) => url === '/auth/refresh')

const Sonda = () => {
  const auth = useAuth()
  return (
    <div>
      <output data-testid="estado">
        {auth.isLoading
          ? 'cargando'
          : auth.sessionUnavailable
            ? 'sin-conexion'
            : (auth.user?.public_id ?? 'anonimo')}
      </output>
      <button type="button" onClick={auth.logout}>
        salir
      </button>
      <button type="button" onClick={() => auth.login('token-b', usuarioB)}>
        entrar-b
      </button>
      <button type="button" onClick={auth.retrySession}>
        reintentar
      </button>
    </div>
  )
}

const montar = (strict = false) => {
  const queryClient = new QueryClient()
  const clear = jest.spyOn(queryClient, 'clear')
  const cancel = jest.spyOn(queryClient, 'cancelQueries')
  const arbol = (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <Sonda />
      </AuthProvider>
    </QueryClientProvider>
  )
  render(strict ? <StrictMode>{arbol}</StrictMode> : arbol)
  return { clear, cancel }
}

const estado = () => screen.getByTestId('estado').textContent

const conSesion = () => {
  mockPost.mockImplementation((url: string) =>
    url === '/auth/refresh'
      ? Promise.resolve({ data: { access_token: 'token-a' } })
      : Promise.resolve({ data: {} })
  )
  mockGet.mockResolvedValue({ data: usuarioA })
}

const montarConSesion = async () => {
  conSesion()
  const montado = montar()
  await waitFor(() => expect(estado()).toBe('usr-a'))
  montado.clear.mockClear()
  montado.cancel.mockClear()
  return montado
}

describe('AuthProvider', () => {
  beforeEach(() => {
    mockPost.mockReset()
    mockGet.mockReset()
    localStorage.clear()
    setAuthToken(null)
  })

  it('con StrictMode el doble montaje hace un solo refresh', async () => {
    conSesion()
    montar(true)

    await waitFor(() => expect(estado()).toBe('usr-a'))
    expect(refreshCalls()).toHaveLength(1)
  })

  it('el logout limpia TODO el cache y revoca en el servidor', async () => {
    const { clear, cancel } = await montarConSesion()

    fireEvent.click(screen.getByText('salir'))

    expect(estado()).toBe('anonimo')
    expect(clear).toHaveBeenCalledTimes(1)
    // 4R 2026-09-28: sin cancelar antes, un GET en vuelo del usuario anterior
    // podia volver a escribir en el cache recien vaciado.
    expect(cancel).toHaveBeenCalledTimes(1)
    expect(cancel.mock.invocationCallOrder[0]).toBeLessThan(clear.mock.invocationCallOrder[0] ?? 0)
    expect(mockPost).toHaveBeenCalledWith('/auth/logout')
    expect(localStorage.getItem('shifty_user')).toBeNull()
  })

  it.each([
    ['sesion vencida', SESSION_EXPIRED_EVENT],
    ['logout en otra pestana', PEER_LOGOUT_EVENT]
  ])('%s limpia el perfil y TODO el cache', async (_caso, evento) => {
    const { clear } = await montarConSesion()

    act(() => {
      window.dispatchEvent(new Event(evento))
    })

    expect(estado()).toBe('anonimo')
    expect(clear).toHaveBeenCalledTimes(1)
  })

  it('un login con otro usuario limpia el cache; con el mismo, no', async () => {
    const { clear } = await montarConSesion()

    fireEvent.click(screen.getByText('entrar-b'))
    expect(estado()).toBe('usr-b')
    expect(clear).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByText('entrar-b'))
    expect(clear).toHaveBeenCalledTimes(1)
  })

  it('otra pestana que entra con otro usuario limpia el cache y carga el nuevo', async () => {
    const { clear } = await montarConSesion()
    mockGet.mockResolvedValue({ data: usuarioB })

    act(() => {
      window.dispatchEvent(new CustomEvent(PEER_SESSION_EVENT, { detail: 'usr-a' }))
    })
    expect(clear).not.toHaveBeenCalled()

    act(() => {
      window.dispatchEvent(new CustomEvent(PEER_SESSION_EVENT, { detail: 'usr-b' }))
    })
    expect(clear).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(estado()).toBe('usr-b'))
  })

  it('un 503 al montar conserva el perfil guardado y ofrece reintentar', async () => {
    localStorage.setItem('shifty_user', JSON.stringify(usuarioA))
    mockPost.mockRejectedValue({
      response: { status: 503, headers: { 'retry-after': '0' }, data: {} },
      message: 'HTTP 503'
    })
    const { clear } = montar()

    await waitFor(() => expect(estado()).toBe('sin-conexion'))
    expect(localStorage.getItem('shifty_user')).not.toBeNull()
    expect(clear).not.toHaveBeenCalled()

    conSesion()
    fireEvent.click(screen.getByText('reintentar'))
    await waitFor(() => expect(estado()).toBe('usr-a'))
  })

  it('un 401 del refresh al montar termina la sesion guardada', async () => {
    localStorage.setItem('shifty_user', JSON.stringify(usuarioA))
    mockPost.mockRejectedValue({ response: { status: 401, data: {} }, message: 'HTTP 401' })
    montar()

    await waitFor(() => expect(estado()).toBe('anonimo'))
    expect(localStorage.getItem('shifty_user')).toBeNull()
  })
})
