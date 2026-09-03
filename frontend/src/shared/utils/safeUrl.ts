/**
 * Valida URLs externas antes de navegar a ellas.
 *
 * Los enlaces de pago / OAuth vienen del backend (Mercado Pago). Aunque el
 * backend es de confianza, forzar `https://` antes de un `window.location`
 * evita que un valor inesperado (config de tienda manipulada, `javascript:`,
 * `data:`) se ejecute como navegacion. Devuelve la URL si es https, o null.
 */
export const asSafeHttpsUrl = (raw: string | null | undefined): string | null => {
  if (!raw) return null
  try {
    const url = new URL(raw)
    return url.protocol === 'https:' ? url.toString() : null
  } catch {
    return null
  }
}

/** Navega a una URL externa solo si es https válida. Devuelve si navegó. */
export const navigateExternal = (raw: string | null | undefined): boolean => {
  const safe = asSafeHttpsUrl(raw)
  if (!safe) return false
  window.location.assign(safe)
  return true
}

/** Deja solo dígitos y un `+` inicial: para armar links de wa.me sin inyección. */
export const sanitizePhoneForUrl = (raw: string | null | undefined): string =>
  (raw ?? '').replace(/[^\d]/g, '')
