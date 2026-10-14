/**
 * Token del cliente que devuelve `/public/otp/verify` (2026-10-14).
 *
 * El backend ata la autogestion ("Mis turnos") y el historial de la seña a
 * quien verifico el OTP: exige este token en `X-Client-Token` ademas de la
 * verificacion en la base. Vive SOLO en memoria (regla 28): nunca
 * localStorage ni sessionStorage. Recargar la pagina lo pierde y pide un
 * codigo nuevo.
 *
 * Modulo aparte del servicio (sin axios) para que la presentacion pueda
 * olvidarlo sin arrastrar el cliente HTTP.
 */

const CLIENT_TOKEN_HEADER = 'X-Client-Token'

let current: { storePublicId: string; token: string } | null = null

export const rememberClientToken = (storePublicId: string, token: string | null | undefined) => {
  current = token ? { storePublicId, token } : null
}

/** Olvida el token ("Salir" o un 403 de verificacion). */
export const forgetClientToken = (): void => {
  current = null
}

/**
 * Hay token para esa tienda. Sin el, una verificacion recordada
 * (`otpSession`) no alcanza: el backend responderia 403.
 */
export const hasClientToken = (storePublicId: string): boolean =>
  current !== null && current.storePublicId === storePublicId

/**
 * Config de axios con el token, o `undefined` si no hay token que mandar.
 * Con tienda, solo si el token es de esa tienda.
 */
export const clientTokenConfig = (
  storePublicId?: string
): { headers: Record<string, string> } | undefined => {
  if (!current) return undefined
  if (storePublicId !== undefined && current.storePublicId !== storePublicId) return undefined
  return { headers: { [CLIENT_TOKEN_HEADER]: current.token } }
}
