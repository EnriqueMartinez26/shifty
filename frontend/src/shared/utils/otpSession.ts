/**
 * Ventana de verificacion OTP recordada mientras la pagina siga abierta.
 *
 * El backend acepta un telefono verificado en los ultimos 30 minutos, pero el
 * front volvia a pedir el codigo en cada corrida del wizard y agotaba el
 * presupuesto de 5 pedidos por hora ante cualquier reintento. Se recuerda
 * {telefono, verificadoEn} por tienda.
 *
 * 2026-10-14: SOLO en memoria. El backend ahora exige ademas el token del
 * cliente que devuelve la verificacion (X-Client-Token), y ese token vive en
 * memoria (regla 28, `PublicBookingService`). Recordar la verificacion en
 * sessionStorage hacia entrar por el atajo despues de recargar, sin token, y
 * rebotar con 403: recargar la pagina pide un codigo nuevo.
 */

const OTP_WINDOW_MINUTES = 30

interface OtpSession {
  phone: string
  verifiedAt: string
}

const sessions = new Map<string, OtpSession>()

/**
 * Solo los digitos del telefono. El backend devuelve el verificado en formato
 * internacional (`+54...`, `normalize_phone`) y la persona lo tipea como
 * quiere: comparar las dos cadenas crudas nunca coincide (F11a-02).
 */
export const phoneDigits = (phone: string): string => phone.replace(/\D/g, '')

export const rememberOtpVerification = (
  storeSlug: string,
  phone: string,
  verifiedAt: string
): void => {
  sessions.set(storeSlug, { phone: phoneDigits(phone), verifiedAt })
}

export const forgetOtpVerification = (storeSlug: string): void => {
  sessions.delete(storeSlug)
}

/** True si el telefono fue verificado en esta pagina dentro de la ventana. */
export const isOtpStillValid = (
  storeSlug: string,
  phone: string,
  now: Date = new Date()
): boolean => {
  const session = sessions.get(storeSlug)
  if (!session || session.phone !== phoneDigits(phone)) return false
  const verifiedAt = new Date(session.verifiedAt).getTime()
  if (Number.isNaN(verifiedAt)) return false
  return now.getTime() - verifiedAt < OTP_WINDOW_MINUTES * 60_000
}
