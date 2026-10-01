import { PAYMENT_POLL_MAX_MS, paymentPollDelayMs } from './paymentPolling'

// F4-05 (2026-09-30): sondeo fijo de 2 s sin corte, unas 900 requests en 30 min
// por cada cliente que volvia de Mercado Pago con el pago pendiente.
describe('paymentPollDelayMs', () => {
  it.each([
    [0, 2000],
    [29_999, 2000],
    [30_000, 5000],
    [120_000, 15000]
  ])('a los %i ms espera %i ms', (elapsedMs, delay) => {
    expect(paymentPollDelayMs(elapsedMs)).toBe(delay)
  })

  it('corta a los 30 minutos', () => {
    expect(PAYMENT_POLL_MAX_MS).toBe(1_800_000)
    expect(paymentPollDelayMs(1_800_000)).toBe(false)
  })

  it('respeta un Retry-After mas largo que el ritmo base', () => {
    expect(paymentPollDelayMs(0, 20)).toBe(20000)
  })

  it('acota el Retry-After a 30 s', () => {
    expect(paymentPollDelayMs(0, 90)).toBe(30000)
  })
})
