import { getDefaultAppRoute } from '../context/roles'

// eslint-disable-next-line no-control-regex -- justamente se buscan caracteres de control
const CONTROL_CHARS = /[\u0000-\u001f\u007f]/

/**
 * Ruta a la que volver despues del login (FF-36, D-20260928-06), o `null` si
 * no es segura. Solo se acepta una ruta interna del mismo origen y dentro del
 * area del rol; el rol sale de `/me` (AuthContext), nunca del JWT (regla 1).
 * Rechaza `//host` y `/\host` (el navegador los toma como otro host), URLs
 * absolutas, `javascript:`, caracteres de control y la propia `/login`.
 */
export const safeReturnPath = (
  from: unknown,
  role: string | null | undefined,
  isGlobalAdmin?: boolean
): string | null => {
  if (typeof from !== 'string' || !from.startsWith('/')) return null
  if (from.startsWith('//') || from.startsWith('/\\') || CONTROL_CHARS.test(from)) return null

  let url: URL
  try {
    url = new URL(from, window.location.origin)
  } catch {
    return null
  }
  if (url.origin !== window.location.origin) return null

  // Se compara la ruta ya normalizada: `/dashboard/../control-global` no
  // cuela bajo el prefijo `/dashboard`.
  const allowedPrefix = getDefaultAppRoute(role, isGlobalAdmin)
  const { pathname } = url
  if (pathname !== allowedPrefix && !pathname.startsWith(`${allowedPrefix}/`)) return null

  return `${pathname}${url.search}${url.hash}`
}
