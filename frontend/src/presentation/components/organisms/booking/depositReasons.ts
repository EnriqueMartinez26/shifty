/** Texto en castellano de los motivos de recargo de la seña (sin la base). */
const DEPOSIT_REASON_LABEL: Record<string, string> = {
  far_notice: 'reservar con mucha antelacion',
  new_client: 'ser tu primera visita',
  absences: 'ausencias anteriores'
}

export const depositReasonsText = (reasons: string[]): string => {
  const partes = reasons
    .filter((reason) => reason !== 'base')
    .map((reason) => DEPOSIT_REASON_LABEL[reason] ?? reason)
  if (partes.length <= 1) return partes.join('')
  return `${partes.slice(0, -1).join(', ')} y ${partes[partes.length - 1]}`
}
