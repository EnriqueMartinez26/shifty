/**
 * Ritmo del sondeo del estado del pago al volver de Mercado Pago (F4-05).
 *
 * El backend concilia a pedido despues de 20 s pendiente y la retencion del
 * turno dura PAYMENT_HOLD_MINUTES (30 por defecto): pasado ese plazo seguir
 * preguntando no cambia nada. Rapido al principio, cuando el webhook suele
 * llegar, y cada vez mas espaciado: unas 145 consultas en 30 min contra las
 * ~900 del sondeo fijo de 2 s.
 */
export const PAYMENT_POLL_MAX_MS = 30 * 60_000

/** Tope del `Retry-After` que se respeta (mismo que queryClientPolicies). */
const MAX_RETRY_AFTER_SECONDS = 30

const baseDelayMs = (elapsedMs: number): number | false => {
  if (elapsedMs < 30_000) return 2000
  if (elapsedMs < 120_000) return 5000
  if (elapsedMs < PAYMENT_POLL_MAX_MS) return 15000
  return false
}

/**
 * Espera hasta la proxima consulta, o `false` pasado el corte. Un
 * `Retry-After` (429/503) alarga la espera, acotado a 30 s; nunca la acorta.
 */
export const paymentPollDelayMs = (
  elapsedMs: number,
  retryAfterSeconds?: number
): number | false => {
  const base = baseDelayMs(elapsedMs)
  if (base === false || retryAfterSeconds === undefined) return base
  return Math.max(base, Math.min(retryAfterSeconds, MAX_RETRY_AFTER_SECONDS) * 1000)
}
