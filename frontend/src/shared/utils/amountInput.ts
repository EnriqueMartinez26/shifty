/**
 * Importes tipeados a mano, en formato es-AR: punto de miles y coma decimal.
 *
 * Revision de la PR #131 (W4, 2026-10-08): el campo de "Confirmar pago" era un
 * `type="number"` y "3.200" llegaba como 3.2, asi que se registraban $3,20.
 * Lo que no se puede leer sin adivinar ("3.2", "3,200") se rechaza con un
 * mensaje que muestra el formato: un importe mal leido es plata mal anotada.
 */
type AmountInputResult = { ok: true; value: number } | { ok: false; error: string }

const FORMAT_ERROR = 'Escribí el importe con punto de miles y coma decimal, por ejemplo 3.200,50.'

// Enteros sin separar o agrupados de a tres con punto, y hasta dos decimales
// despues de la coma.
const ES_AR_AMOUNT = /^(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?$/

export const parseAmountInput = (text: string): AmountInputResult => {
  const trimmed = text.trim()
  if (trimmed === '') return { ok: false, error: 'Ingresá el importe.' }
  const match = ES_AR_AMOUNT.exec(trimmed.replace(/^\$\s*/, ''))
  if (!match) return { ok: false, error: FORMAT_ERROR }
  const integerPart = (match[1] ?? '').replace(/\./g, '')
  const value = Number(`${integerPart}.${match[2] ?? '0'}`)
  if (!(value > 0)) return { ok: false, error: 'El importe tiene que ser mayor a cero.' }
  return { ok: true, value }
}

/** El texto que `parseAmountInput` vuelve a leer como el mismo importe. */
export const formatAmountInput = (amount: number): string => {
  const cents = Math.round(amount * 100)
  const integerPart = String(Math.floor(cents / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, '.')
  const decimals = cents % 100
  return decimals === 0 ? integerPart : `${integerPart},${String(decimals).padStart(2, '0')}`
}
