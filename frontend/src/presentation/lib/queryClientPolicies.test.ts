import { QueryClient } from '@tanstack/react-query'

import {
  ConflictError,
  ForbiddenError,
  InternalServerError,
  NetworkError,
  NotFoundError,
  PaymentRequiredError,
  RateLimitError,
  ServiceUnavailableError,
  ValidationError
} from '@shared/errors'

import { refreshSubscriptionOnSuspension, shouldRetryQuery } from './queryClientPolicies'
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
