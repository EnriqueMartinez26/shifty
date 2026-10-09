import { QueryClient } from '@tanstack/react-query'

import {
  ConflictError,
  ForbiddenError,
  InternalServerError,
  NetworkError,
  NotFoundError,
  PaymentRequiredError,
  RateLimitError,
  RequestCanceledError,
  RequestTimeoutError,
  ServiceUnavailableError,
  ValidationError
} from '@shared/errors'

import {
  queryRetryDelay,
  refreshSubscriptionOnSuspension,
  shouldNotifyQueryError,
  shouldRetryQuery
} from './queryClientPolicies'
import { STORE_SUBSCRIPTION_QUERY_KEY } from '../hooks/useStores'

// useStores, que define la query key, importa el servicio real, que arrastra el
// cliente HTTP y su import.meta; aca solo importa la key.
jest.mock('@application/services/StoreSettingsService', () => ({ storeSettingsService: {} }))

describe('shouldRetryQuery', () => {
  it.each([
    ['402', new PaymentRequiredError('x', { statusCode: 402 })],
    ['403', new ForbiddenError('x', { statusCode: 403 })],
    ['404', new NotFoundError('x', { statusCode: 404 })],
    ['409', new ConflictError('x', { statusCode: 409 })],
    ['422', new ValidationError('x', { statusCode: 422 })],
    ['429', new RateLimitError('x', { statusCode: 429 })]
  ])('no reintenta un %s: repetirlo no cambia la respuesta', (_status, error) => {
    expect(shouldRetryQuery(0, error)).toBe(false)
  })

  it('no reintenta una lectura que vencio su timeout (D-20260930-02)', () => {
    // F4-04 b (2026-10-01): sin esto un GET colgado esperaba 15 s, se
    // reintentaba y esperaba otros 15 s antes de mostrar el error.
    const timeout = new RequestTimeoutError('x', { errorCode: 'REQUEST_TIMEOUT', statusCode: 0 })

    expect(shouldRetryQuery(0, timeout)).toBe(false)
    // Tambien envuelto por BaseService (el original en `originalError`).
    expect(shouldRetryQuery(0, Object.assign(new Error('x'), { originalError: timeout }))).toBe(
      false
    )
  })

  it('no reintenta una consulta cancelada a proposito', () => {
    // 2026-10-02: una consulta cancelada por react-query se reportaba como
    // error de red a Sentry, y como NetworkError tambien se reintentaba.
    const canceled = new RequestCanceledError('x', {
      errorCode: 'REQUEST_CANCELED',
      statusCode: 0
    })

    expect(shouldRetryQuery(0, canceled)).toBe(false)
    expect(shouldRetryQuery(0, Object.assign(new Error('x'), { originalError: canceled }))).toBe(
      false
    )
  })

  it.each([
    ['la falta de red', new NetworkError('x')],
    ['un 500', new InternalServerError('x', { statusCode: 500 })],
    ['un 503', new ServiceUnavailableError('x', { statusCode: 503 })],
    ['un error que no vino del cliente HTTP', new Error('x')]
  ])('reintenta una vez %s', (_caso, error) => {
    expect(shouldRetryQuery(0, error)).toBe(true)
    expect(shouldRetryQuery(1, error)).toBe(false)
  })
})

describe('queryRetryDelay (F4-04)', () => {
  it('respeta el Retry-After del servidor cuando llega', () => {
    const error = new ServiceUnavailableError('x', { statusCode: 503, retryAfter: 5 })

    expect(queryRetryDelay(0, error)).toBe(5_000)
  })

  it('acota un Retry-After desmedido', () => {
    const error = new ServiceUnavailableError('x', { statusCode: 503, retryAfter: 3_600 })

    expect(queryRetryDelay(0, error)).toBe(30_000)
  })

  it.each([
    ['sin Retry-After', new ServiceUnavailableError('x', { statusCode: 503 })],
    ['con un Retry-After ilegible', new ServiceUnavailableError('x', { retryAfter: 'pronto' })],
    ['ante un error que no vino del cliente HTTP', new Error('x')]
  ])('%s usa la espera por defecto de react-query', (_caso, error) => {
    expect(queryRetryDelay(0, error)).toBe(1_000)
    expect(queryRetryDelay(1, error)).toBe(2_000)
  })
})

describe('shouldNotifyQueryError', () => {
  it('avisa si fallo un refresco con datos ya en pantalla', () => {
    expect(shouldNotifyQueryError({ state: { data: [] } })).toBe(true)
  })

  it('no avisa la primera carga: la pantalla ya muestra su propio error', () => {
    expect(shouldNotifyQueryError({ state: { data: undefined } })).toBe(false)
  })
})

describe('refreshSubscriptionOnSuspension', () => {
  const setup = () => {
    const queryClient = new QueryClient()
    const invalidate = jest.spyOn(queryClient, 'invalidateQueries').mockResolvedValue()
    return { queryClient, invalidate }
  }

  it('un SUBSCRIPTION_SUSPENDED refresca el estado del plan', () => {
    const { queryClient, invalidate } = setup()
    const error = new PaymentRequiredError('Suscripcion suspendida', {
      errorCode: 'SUBSCRIPTION_SUSPENDED',
      statusCode: 402
    })

    refreshSubscriptionOnSuspension(error, queryClient)

    expect(invalidate).toHaveBeenCalledWith({ queryKey: STORE_SUBSCRIPTION_QUERY_KEY })
  })

  it('otro error no toca la suscripcion', () => {
    const { queryClient, invalidate } = setup()

    refreshSubscriptionOnSuspension(
      new ConflictError('x', { errorCode: 'APPOINTMENT_CONFLICT' }),
      queryClient
    )

    expect(invalidate).not.toHaveBeenCalled()
  })
})
