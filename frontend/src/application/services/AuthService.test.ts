// F9-08 (2026-09-30): cobertura del servicio de sesion. Cada path queda
// literal (regla 23) con su verbo y su cuerpo; el refresh no hace su propio
// POST, delega en el refresh coordinado del cliente HTTP (F4-01, F4-02).
const mockGet = jest.fn()
const mockPost = jest.fn()
const mockPut = jest.fn()
const mockRefreshSession = jest.fn()

jest.mock('@infrastructure/http/client', () => ({
  __esModule: true,
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
    put: (...args: unknown[]) => mockPut(...args)
  },
  refreshSession: () => mockRefreshSession()
}))

import { authService } from './AuthService'

describe('AuthService', () => {
  beforeEach(() => {
    mockGet.mockReset()
    mockPost.mockReset()
    mockPut.mockReset()
    mockRefreshSession.mockReset()
    mockPost.mockResolvedValue({ data: { message: 'ok' } })
  })

  it('login manda las credenciales por POST y devuelve el token', async () => {
    mockPost.mockResolvedValue({ data: { access_token: 'tok-1' } })

    const result = await authService.login({ email: 'ana@x.com', password: 'secreta-larga' })

    expect(mockPost).toHaveBeenCalledWith('/auth/login', {
      email: 'ana@x.com',
      password: 'secreta-larga'
    })
    expect(result).toEqual({ access_token: 'tok-1' })
  })

  it('fetchCurrentUser pide /me por GET', async () => {
    const user = { email: 'ana@x.com', role: 'admin', store_id: 's-1', public_id: 'u-1' }
    mockGet.mockResolvedValue({ data: user })

    await expect(authService.fetchCurrentUser()).resolves.toEqual(user)
    expect(mockGet).toHaveBeenCalledWith('/me')
  })

  it('logout revoca la sesion por POST sin cuerpo', async () => {
    await authService.logout()

    expect(mockPost).toHaveBeenCalledWith('/auth/logout')
  })

  it('forgot y reset de clave van por POST con su payload', async () => {
    await authService.forgotPassword({ email: 'ana@x.com' })
    await authService.resetPassword({ token: 't-1', new_password: 'nueva-clave-12' })

    expect(mockPost).toHaveBeenNthCalledWith(1, '/auth/forgot-password', { email: 'ana@x.com' })
    expect(mockPost).toHaveBeenNthCalledWith(2, '/auth/reset-password', {
      token: 't-1',
      new_password: 'nueva-clave-12'
    })
  })

  it('change-password va por PUT, no por POST', async () => {
    mockPut.mockResolvedValue({ data: undefined })

    await authService.changePassword({ current_password: 'vieja', new_password: 'nueva-clave-12' })

    expect(mockPut).toHaveBeenCalledWith('/auth/change-password', {
      current_password: 'vieja',
      new_password: 'nueva-clave-12'
    })
    expect(mockPost).not.toHaveBeenCalled()
  })

  it('refreshSession delega en el refresh coordinado del cliente', async () => {
    const refreshed = { kind: 'ok', token: 'tok-2' }
    mockRefreshSession.mockResolvedValue(refreshed)

    await expect(authService.refreshSession()).resolves.toBe(refreshed)
    expect(mockRefreshSession).toHaveBeenCalledTimes(1)
    expect(mockPost).not.toHaveBeenCalled()
  })
})
