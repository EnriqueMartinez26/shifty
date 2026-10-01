import { currencyFmtEsAr } from '../../../lib/formatters'

export const numberFormatter = new Intl.NumberFormat('es-AR', {
  maximumFractionDigits: 0
})

const percentFormatter = new Intl.NumberFormat('es-AR', {
  maximumFractionDigits: 1
})

export const formatCurrency = (value: number | string | null | undefined) =>
  currencyFmtEsAr.format(Number(value ?? 0))

export const formatPercent = (value: number | null | undefined) =>
  `${percentFormatter.format(Number(value ?? 0))}%`
