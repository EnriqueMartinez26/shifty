import type { QueryClient } from '@tanstack/react-query'

import { getErrorCode, getHttpStatus, getRetryAfterSeconds } from '@shared/errors/getErrorMessage'

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
 * respuesta, 5xx o un error que no vino del cliente HTTP. Una lectura que
 * vencio su timeout de 15 s no se reintenta (D-20260930-02), y una que se
 * cancelo a proposito tampoco: nadie espera ya su resultado.
 */
const NON_RETRYABLE_CODES: ReadonlySet<string> = new Set(['REQUEST_TIMEOUT', 'REQUEST_CANCELED'])

export const shouldRetryQuery = (failureCount: number, error: unknown): boolean => {
  if (failureCount >= MAX_QUERY_RETRIES) return false
  if (NON_RETRYABLE_CODES.has(getErrorCode(error) ?? '')) return false
  const status = getHttpStatus(error)
  return status === undefined || status < 400 || status >= 500
}

/** Tope de espera aunque el servidor pida mas (mismo que sessionSync). */
const MAX_RETRY_DELAY_MS = 30_000
const BASE_RETRY_DELAY_MS = 1_000

/**
 * Espera antes del reintento de `shouldRetryQuery` (F4-04): el `Retry-After`
 * de un 503 si llego, acotado; si no, el backoff por defecto de react-query.
 */
export const queryRetryDelay = (failureCount: number, error: unknown): number => {
  const retryAfter = getRetryAfterSeconds(error)
  if (retryAfter !== undefined) return Math.min(retryAfter * 1_000, MAX_RETRY_DELAY_MS)
  return Math.min(BASE_RETRY_DELAY_MS * 2 ** failureCount, MAX_RETRY_DELAY_MS)
}

/**
 * Una query que falla en la primera carga ya tiene su error en la pantalla
 * (QueryErrorNotice o equivalente); un aviso global lo duplicaria. Solo se
 * avisa cuando falla un refresco y la pantalla sigue mostrando datos viejos.
 */
export const shouldNotifyQueryError = (query: { state: { data: unknown } }): boolean =>
  query.state.data !== undefined

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
