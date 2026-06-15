export const currencyFmtEsAr = new Intl.NumberFormat('es-AR', {
  style: 'currency',
  currency: 'ARS',
  maximumFractionDigits: 0
})

export const formatCurrencyEsAr = (value: string | number, currency = 'ARS') =>
  new Intl.NumberFormat('es-AR', {
    style: 'currency',
    currency,
    maximumFractionDigits: 0
  }).format(Number(value || 0))

export const formatDateEsAr = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat('es-AR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric'
      }).format(new Date(value))
    : 'Sin fecha'

export const formatDateTimeEsAr = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat('es-AR', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      }).format(new Date(value))
    : 'Sin actividad'
