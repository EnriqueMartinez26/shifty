/** Texto en castellano de los motivos de recargo de la seña (sin la base). */
const DEPOSIT_REASON_LABEL: Record<string, string> = {
  far_notice: 'reservar con mucha antelacion',
  new_client: 'ser tu primera visita',
  absences: 'ausencias anteriores'
}

/**
 * Desglose de la seña en pesos que siempre cierra: base + recargo = total.
 * Antes decia "base mas X% del precio", que no sumaba cuando el backend
 * topeaba la seña al precio del servicio (review 2026-09-11, LOW).
 */
export const depositBreakdownText = (
  preview: {
    amount: number
    base_amount: number
    extra_percent: number
    price: number
    reasons: string[]
  },
  fmt: (n: number) => string
): string => {
  const recargo = Math.max(0, preview.amount - preview.base_amount)
  const topeada = preview.price > 0 && preview.amount >= preview.price
  const motivo = topeada
    ? 'la seña se topea al precio del servicio'
    : `${preview.extra_percent}% del precio`
  return `Incluye ${fmt(preview.base_amount)} de seña base mas ${fmt(recargo)} por ${depositReasonsText(preview.reasons)} (${motivo}).`
}

export const depositReasonsText = (reasons: string[]): string => {
  const partes = reasons
    .filter((reason) => reason !== 'base')
    .map((reason) => DEPOSIT_REASON_LABEL[reason] ?? reason)
  if (partes.length <= 1) return partes.join('')
  return `${partes.slice(0, -1).join(', ')} y ${partes[partes.length - 1]}`
}
