import React from 'react'

import { QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'

import { renderHook, waitFor } from '@testing-library/react'

import apiClient from '@infrastructure/http/client'
import {
  ConflictErrorHandler,
  ForbiddenErrorHandler,
  InternalServerErrorHandler,
  NetworkErrorHandler,
  NotFoundErrorHandler,
  setToastSink,
  TransientErrorHandler,
  UnauthorizedErrorHandler,
  ValidationErrorHandler
} from '@infrastructure/setup/SpecificHandlers'

import { GlobalErrorHandler } from '@shared/errors/GlobalErrorHandler'

import { useManagedDomainUsers } from './useManagedDomainUsers'
import { shouldNotifyQueryError, shouldRetryQuery } from '../lib/queryClientPolicies'

// runtime-env lee import.meta, que ts-jest no compila.
jest.mock('@infrastructure/http/runtime-env', () => ({
  __esModule: true,
  getRuntimeEnv: () => ({ apiUrl: 'http://test-api', dev: true })
}))

// queryClientPolicies importa la key de useStores, que arrastra este servicio.
jest.mock('@application/services/StoreSettingsService', () => ({ storeSettingsService: {} }))

/** La busqueda vieja queda colgada hasta que su signal la aborta. */
const adapter = jest.fn(
  (config: InternalAxiosRequestConfig): Promise<AxiosResponse> =>
    new Promise((resolve, reject) => {
      const params = (config.params ?? {}) as { q?: string }
      if (params.q === 'an') {
        config.signal?.addEventListener?.('abort', () => reject(new Error('aborted')))
        return
      }
      resolve({ data: [], status: 200, statusText: 'OK', headers: {}, config })
    })
)

/** Los mismos handlers, en el mismo orden, que registra main.tsx. */
const globalHandlerLikeMain = () => {
  const handler = new GlobalErrorHandler()
  handler.registerHandler(new ValidationErrorHandler())
  handler.registerHandler(new NotFoundErrorHandler())
  handler.registerHandler(new UnauthorizedErrorHandler())
  handler.registerHandler(new ForbiddenErrorHandler())
  handler.registerHandler(new ConflictErrorHandler())
  handler.registerHandler(new InternalServerErrorHandler())
  handler.registerHandler(new NetworkErrorHandler())
  handler.registerHandler(new TransientErrorHandler())
  return handler
}

/**
 * 2026-10-02: una consulta cancelada por react-query se reportaba como error
 * de red a Sentry. Tipear en el buscador de usuarios reemplaza la consulta y
 * react-query aborta la vieja; BaseService la registraba como
 * "[ERROR] UserService - NetworkError: No se pudo conectar con el servidor."
 * en cada tecla. Recorre la cadena real: hook, UserService (BaseService),
 * HttpUserRepository, apiClient y las politicas y handlers de main.tsx.
 */
describe('una busqueda reemplazada no es un error', () => {
  let consoleError: jest.SpyInstance
  let consoleWarn: jest.SpyInstance
  const sink = jest.fn()
  const originalAdapter = apiClient.defaults.adapter

  beforeEach(() => {
    adapter.mockClear()
    sink.mockReset()
    setToastSink(sink)
    apiClient.defaults.adapter = adapter
    consoleError = jest.spyOn(console, 'error').mockImplementation(() => {})
    consoleWarn = jest.spyOn(console, 'warn').mockImplementation(() => {})
  })

  afterEach(() => {
    apiClient.defaults.adapter = originalAdapter
    consoleError.mockRestore()
    consoleWarn.mockRestore()
  })

  it('la busqueda de usuarios abortada no se registra, no avisa y no se reintenta', async () => {
    const globalHandler = globalHandlerLikeMain()
    const onError = jest.fn((error: unknown, query: { state: { data: unknown } }) => {
      if (shouldNotifyQueryError(query)) void globalHandler.handle(error)
    })
    const retry = jest.fn(shouldRetryQuery)
    const queryClient = new QueryClient({
      queryCache: new QueryCache({ onError }),
      defaultOptions: { queries: { retry, retryDelay: 0 } }
    })
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )

    const { result, rerender } = renderHook(
      ({ q }: { q: string }) => useManagedDomainUsers({ limit: 100, q }),
      { wrapper, initialProps: { q: 'an' } }
    )
    await waitFor(() => expect(adapter).toHaveBeenCalledTimes(1))

    rerender({ q: 'ana' })
    await waitFor(() => expect(result.current.data).toEqual([]))
    // Que terminen de asentarse los rechazos de la consulta abortada.
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(adapter.mock.calls[0]?.[0].signal?.aborted).toBe(true)
    expect(adapter).toHaveBeenCalledTimes(2)
    expect(result.current.error).toBeNull()
    expect(consoleError).not.toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
    expect(retry).not.toHaveBeenCalled()
    expect(sink).not.toHaveBeenCalled()
  })

  it('la consulta abortada no se reintenta aunque llegue a la politica', async () => {
    const controller = new AbortController()
    controller.abort()
    const error: unknown = await apiClient
      .get('/users/', { signal: controller.signal })
      .catch((e) => e)

    expect(shouldRetryQuery(0, error)).toBe(false)
  })
})
