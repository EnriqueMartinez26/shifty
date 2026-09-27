import type { QueryClient } from '@tanstack/react-query'

import { getErrorCode, getHttpStatus } from '@shared/errors/getErrorMessage'

import { STORE_SUBSCRIPTION_QUERY_KEY } from '../hooks/useStores'

/**
 * Politicas globales del QueryClient (main.tsx), aca para poder testearlas:
 * main.tsx monta la app al importarse y esta fuera de la cobertura.
 */

const MAX_QUERY_RETRIES = 1

/**
 * Un 4xx es determinista (402 suspendida, 403, 404, 409, 422, 429): repetir
 * el GET no lo arregla, solo demora el error y suma carga (un 429 reintentado
 * empeora el limite). Se reintenta una vez lo que puede ser pasajero: sin
 * respuesta, 5xx o un error que no vino del cliente HTTP.
 */
export const shouldRetryQuery = (failureCount: number, error: unknown): boolean => {
  if (failureCount >= MAX_QUERY_RETRIES) return false
  const status = getHttpStatus(error)
  return status === undefined || status < 400 || status >= 500
}

/**
 * Una escritura rechazada por suscripcion suspendida (402) significa que el
 * estado del plan que muestra el panel quedo viejo: se refresca para que el
 * aviso de solo lectura aparezca ya, sin esperar al staleTime.
 */
export const refreshSubscriptionOnSuspension = (error: unknown, queryClient: QueryClient) => {
  if (getErrorCode(error) === 'SUBSCRIPTION_SUSPENDED') {
    void queryClient.invalidateQueries({ queryKey: STORE_SUBSCRIPTION_QUERY_KEY })
  }
}
