import { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'

import { RequestTimeoutError } from '@shared/errors'
import { getErrorCode, getErrorMessage } from '@shared/errors/getErrorMessage'

// runtime-env lee import.meta, que ts-jest no compila.
jest.mock('./runtime-env', () => ({
  __esModule: true,
  getRuntimeEnv: () => ({ apiUrl: 'http://test-api', dev: true })
}))

const ok = (config: InternalAxiosRequestConfig): Promise<AxiosResponse> =>
  Promise.resolve({ data: {}, status: 200, statusText: 'OK', headers: {}, config })

/**
 * D-20260930-02 (F4-04 b), 2026-10-01: sin ningun timeout una lectura colgada
 * dejaba la pantalla cargando hasta que nginx cortaba a los 30 s. Las lecturas
 * cortan a los 15 s; las escrituras siguen sin timeout en el cliente, porque
 * un POST que el servidor aplico no puede darse por fallido aca.
 */
describe('apiClient: timeout solo en lecturas (D-20260930-02)', () => {
  it('un GET sale con timeout de 15 s', async () => {
    const { default: apiClient } = await import('./client')
    const adapter = jest.fn(ok)

    await apiClient.get('/reports/summary', { adapter })

    expect(adapter.mock.calls[0]?.[0].timeout).toBe(15_000)
  })

  it.each(['post', 'patch', 'put', 'delete'] as const)('un %s sale sin timeout', async (method) => {
    const { default: apiClient } = await import('./client')
    const adapter = jest.fn(ok)

    await apiClient.request({ url: '/appointments/', method, adapter })

    expect(adapter.mock.calls[0]?.[0].timeout ?? 0).toBe(0)
  })

  it('un GET con timeout propio lo conserva', async () => {
    const { default: apiClient } = await import('./client')
    const adapter = jest.fn(ok)

    await apiClient.get('/reports/export', { adapter, timeout: 60_000 })

    expect(adapter.mock.calls[0]?.[0].timeout).toBe(60_000)
  })

  it('pide a axios que un timeout se distinga de un request abortado', async () => {
    // Sin clarifyTimeoutError axios usa ECONNABORTED tanto para el timeout
    // como para "Request aborted"; con el, el timeout es ETIMEDOUT.
    const { default: apiClient } = await import('./client')

    expect(apiClient.defaults.transitional?.clarifyTimeoutError).toBe(true)
  })

  it('una lectura que vence da un error tipado con su propio mensaje', async () => {
    const { default: apiClient } = await import('./client')
    const adapter = jest.fn((config: InternalAxiosRequestConfig) =>
      Promise.reject(
        new AxiosError('timeout of 15000ms exceeded', AxiosError.ETIMEDOUT, config, null)
      )
    )

    const error: unknown = await apiClient.get('/ledger/clients', { adapter }).catch((e) => e)

    expect(error).toBeInstanceOf(RequestTimeoutError)
    expect(getErrorCode(error)).toBe('REQUEST_TIMEOUT')
    expect(getErrorMessage(error, 'otro texto')).toBe(
      'La consulta tardó demasiado. Probá de nuevo.'
    )
    expect(adapter).toHaveBeenCalledTimes(1)
  })
})
