/**
 * Unico formateador de importes del front: pesos argentinos (es-AR), sin
 * centavos, con separador de miles. Antes cada pantalla armaba el suyo y el
 * mismo precio salia "$8500", "$ 4.200" o "$1500.0" (QA 2026-10-02).
 *
 * Un valor ausente o que no es un numero se muestra como cero: la API manda
 * los importes como numero o como texto decimal.
 */
const formatters = new Map<string, Intl.NumberFormat>()

const formatterFor = (currency: string): Intl.NumberFormat => {
  let formatter = formatters.get(currency)
  if (!formatter) {
    formatter = new Intl.NumberFormat('es-AR', {
      style: 'currency',
      currency,
      maximumFractionDigits: 0
    })
    formatters.set(currency, formatter)
  }
  return formatter
}

export const formatCurrency = (
  value: number | string | null | undefined,
  currency = 'ARS'
): string => {
  const amount = Number(value ?? 0)
  return formatterFor(currency).format(Number.isFinite(amount) ? amount : 0)
}
