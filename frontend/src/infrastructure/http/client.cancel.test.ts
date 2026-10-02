import { type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'

import { NetworkError } from '@shared/errors'
import { getErrorCode } from '@shared/errors/getErrorMessage'
import { GlobalErrorHandler } from '@shared/errors/GlobalErrorHandler'

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
} from '../setup/SpecificHandlers'

// runtime-env lee import.meta, que ts-jest no compila.
jest.mock('./runtime-env', () => ({
  __esModule: true,
  getRuntimeEnv: () => ({ apiUrl: 'http://test-api', dev: true })
}))

const ok = (config: InternalAxiosRequestConfig): Promise<AxiosResponse> =>
  Promise.resolve({ data: [], status: 200, statusText: 'OK', headers: {}, config })

/** Un GET cuyo signal ya fue abortado, como el de una busqueda reemplazada. */
const canceledRead = async (): Promise<unknown> => {
  const { default: apiClient } = await import('./client')
  const controller = new AbortController()
  controller.abort()
  return apiClient
    .get('/ledger/clients', { adapter: ok, signal: controller.signal })
    .catch((e) => e)
}

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
 * de red a Sentry. Los PR #83 y #96 pasan el `signal` de react-query a axios
 * para cortar las lecturas reemplazadas (buscadores, grilla publica, reportes,
 * usuarios); axios la rechaza con ERR_CANCELED y el cliente la convertia en
 * NetworkError ("No se pudo conectar con el servidor."), que BaseService
 * registraba como ERROR y los handlers globales anunciaban como falta de red.
 */
describe('apiClient: una lectura cancelada no es un error de red', () => {
  let consoleError: jest.SpyInstance
  const sink = jest.fn()

  beforeEach(() => {
    sink.mockReset()
    setToastSink(sink)
    consoleError = jest.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    consoleError.mockRestore()
  })

  it('sale con su propio codigo, no como NetworkError', async () => {
    const error = await canceledRead()

    expect(error).not.toBeInstanceOf(NetworkError)
    expect(getErrorCode(error)).toBe('REQUEST_CANCELED')
  })

  it('los handlers globales no avisan nada ni la registran como error', async () => {
    const error = await canceledRead()

    await globalHandlerLikeMain().handle(error)

    expect(sink).not.toHaveBeenCalled()
    expect(consoleError).not.toHaveBeenCalled()
  })
})
