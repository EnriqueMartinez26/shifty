import { formatArgentinaDateDisplay, formatArgentinaTime } from '@shared/utils/argentinaTime'

import { reportUnreadableInstant } from './reportUnreadableInstant'

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

/**
 * `'es-AR'` es un locale, no una zona: sin `timeZone` estos formateadores
 * mostraban la hora del navegador. Un periodo que termina a las 02:00Z son
 * las 23:00 del dia anterior en Argentina, asi que el panel de superadmin
 * podia imprimir "01/09/2026" al lado de un "Vencida hace 1 d" calculado en
 * hora argentina. El dueno unico del formato de fecha es `argentinaTime`.
 *
 * Tambien dejan de romper con un valor ilegible: `Intl.format(new Date('x'))`
 * lanza `RangeError`, mientras que estos devuelven el texto de respaldo.
 */
/**
 * Un valor presente pero ilegible no es lo mismo que uno ausente: el primero
 * es dato corrupto y se reporta, el segundo es el caso normal y no.
 */
const formattedDate = (value: string | null, field: string): string => {
  if (!value) return ''
  const fecha = formatArgentinaDateDisplay(value)
  if (!fecha) reportUnreadableInstant(field, value)
  return fecha
}

export const formatDateEsAr = (value: string | null) =>
  formattedDate(value, 'formatDateEsAr') || 'Sin fecha'

export const formatDateTimeEsAr = (value: string | null) => {
  const fecha = formattedDate(value, 'formatDateTimeEsAr')
  return fecha ? `${fecha}, ${formatArgentinaTime(value ?? '')}` : 'Sin actividad'
}
