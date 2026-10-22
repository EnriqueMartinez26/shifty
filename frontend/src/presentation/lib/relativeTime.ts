/**
 * Cuanto paso desde un instante ("hace 5 min", "hace 3 h", "hace 2 d"). Lo
 * comparten la campana de avisos y la limpieza de reservas del portal. Un
 * instante ilegible devuelve '' en vez de "hace NaN d".
 */
export const formatRelative = (isoDate: string): string => {
  const created = new Date(isoDate).getTime()
  if (Number.isNaN(created)) return ''
  const minutes = Math.floor((Date.now() - created) / 60000)
  if (minutes < 1) return 'recién'
  if (minutes < 60) return `hace ${minutes} min`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `hace ${hours} h`
  return `hace ${Math.floor(hours / 24)} d`
}
