/**
 * Espejo de `core/validation.py::normalize_client_phone` y del
 * `client_phone: Field(min_length=6, max_length=30)` de la reserva publica:
 * solo digitos y separadores (espacio, guion, parentesis, +), al menos 6
 * digitos, hasta 30 caracteres. Antes el front aceptaba cualquier texto no
 * vacio y el 422 se leia como "el horario podria estar ocupado" (QA
 * 2026-10-02).
 */
const CLIENT_PHONE_MIN_DIGITS = 6
const CLIENT_PHONE_MAX_LENGTH = 30

export const isValidClientPhone = (raw: string): boolean => {
  const value = raw.trim()
  if (value.length < CLIENT_PHONE_MIN_DIGITS || value.length > CLIENT_PHONE_MAX_LENGTH) return false
  const digits = value.replace(/[\s\-()+]/g, '')
  return /^\d+$/.test(digits) && digits.length >= CLIENT_PHONE_MIN_DIGITS
}

export const CLIENT_PHONE_HINT =
  'Ingresá un teléfono con al menos 6 dígitos (podés usar espacios, guiones, paréntesis o +).'
