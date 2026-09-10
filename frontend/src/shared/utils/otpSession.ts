/**
 * Ventana de verificacion OTP recordada en el dispositivo.
 *
 * El backend acepta un telefono verificado en los ultimos 30 minutos
 * (``is_recently_verified``), pero el front volvia a pedir el codigo en cada
 * corrida del wizard y agotaba el presupuesto de 5 pedidos por hora ante
 * cualquier reintento. Se guarda {telefono, verificadoEn} en sessionStorage,
 * por tienda; se lee con try/catch porque el storage puede no existir.
 */

export const OTP_WINDOW_MINUTES = 30

interface OtpSession {
  phone: string
  verifiedAt: string
}

const key = (storeSlug: string): string => `shifty:otp:${storeSlug}`

const digits = (phone: string): string => phone.replace(/\D/g, '')

export const rememberOtpVerification = (
  storeSlug: string,
  phone: string,
  verifiedAt: string
): void => {
  try {
    const session: OtpSession = { phone: digits(phone), verifiedAt }
    window.sessionStorage.setItem(key(storeSlug), JSON.stringify(session))
  } catch {
    // sin storage (privado, bloqueado): simplemente no se recuerda
  }
}

export const forgetOtpVerification = (storeSlug: string): void => {
  try {
    window.sessionStorage.removeItem(key(storeSlug))
  } catch {
    // idem
  }
}

/** True si el telefono fue verificado en este dispositivo dentro de la ventana. */
export const isOtpStillValid = (
  storeSlug: string,
  phone: string,
  now: Date = new Date()
): boolean => {
  try {
    const raw = window.sessionStorage.getItem(key(storeSlug))
    if (!raw) return false
    const session = JSON.parse(raw) as Partial<OtpSession>
    if (!session.phone || !session.verifiedAt || session.phone !== digits(phone)) return false
    const verifiedAt = new Date(session.verifiedAt).getTime()
    if (Number.isNaN(verifiedAt)) return false
    return now.getTime() - verifiedAt < OTP_WINDOW_MINUTES * 60_000
  } catch {
    return false
  }
}
