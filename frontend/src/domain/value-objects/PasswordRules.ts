// Single client-side source of truth for the rules of a password that is being
// SET (reset, own change, user create/edit, superadmin). D-20261001-01 (backend
// half in PR #80): 6 to 64 characters, at most 72 bytes in UTF-8, at least one
// letter and one digit. The denylist stays server-side only.
//
// Characters are Unicode code points (like the backend), not UTF-16 units:
// `value.length` would count an emoji as 2. The 72-byte cap is bcrypt's input
// limit: over it the backend answers 422 instead of truncating, so the UI says
// so before sending.
//
// LOGIN is a different contract (1 to 128 characters, no composition rule) and
// does not go through `validateNewPassword`: it only reuses the 128 cap.
export const PASSWORD_MIN_LENGTH = 6
export const PASSWORD_MAX_LENGTH = 64
export const PASSWORD_MAX_BYTES = 72
export const LOGIN_PASSWORD_MAX_LENGTH = 128

/**
 * Shown when the server answers 422 on a password that already passed
 * `validateNewPassword`: what is left is the common-passwords denylist, which
 * only the server knows.
 */
export const PASSWORD_REJECTED_MESSAGE =
  'La contraseña no es aceptable: es demasiado común o no cumple las reglas. Elegí otra'

// UTF-8 size by code point (same result as `TextEncoder`, lone surrogates count
// as 3 like its U+FFFD replacement). Not `TextEncoder` on purpose: jest's jsdom
// has none and `src/test/setup.ts` shims it at one byte per character, which
// would hide exactly the bug this cap exists to catch.
function utf8ByteLength(codePoints: string[]): number {
  let bytes = 0
  for (const char of codePoints) {
    const codePoint = char.codePointAt(0) ?? 0
    if (codePoint < 0x80) bytes += 1
    else if (codePoint < 0x800) bytes += 2
    else if (codePoint < 0x10000) bytes += 3
    else bytes += 4
  }
  return bytes
}

/**
 * Returns the Spanish message of the first rule the password breaks, or `null`
 * when it is acceptable. The value is judged exactly as typed: no trim, no
 * normalization (a password is sent as the user wrote it).
 */
export function validateNewPassword(value: string): string | null {
  const codePoints = Array.from(value)

  if (codePoints.length < PASSWORD_MIN_LENGTH) {
    return `La contraseña debe tener al menos ${PASSWORD_MIN_LENGTH} caracteres`
  }
  if (codePoints.length > PASSWORD_MAX_LENGTH) {
    return `La contraseña no puede tener más de ${PASSWORD_MAX_LENGTH} caracteres`
  }
  if (utf8ByteLength(codePoints) > PASSWORD_MAX_BYTES) {
    return `La contraseña ocupa más de ${PASSWORD_MAX_BYTES} bytes (los acentos, la ñ, los símbolos y los emojis ocupan más de uno)`
  }
  if (!/\p{L}/u.test(value)) {
    return 'La contraseña debe incluir al menos una letra'
  }
  // Python str.isdigit accepts Nd and these Unicode Numeric_Type=Digit ranges.
  if (
    !/[\p{Nd}\u{b2}-\u{b3}\u{b9}\u{1369}-\u{1371}\u{19da}\u{2070}\u{2074}-\u{2079}\u{2080}-\u{2089}\u{2460}-\u{2468}\u{2474}-\u{247c}\u{2488}-\u{2490}\u{24ea}\u{24f5}-\u{24fd}\u{24ff}\u{2776}-\u{277e}\u{2780}-\u{2788}\u{278a}-\u{2792}\u{10a40}-\u{10a43}\u{10e60}-\u{10e68}\u{11052}-\u{1105a}\u{1f100}-\u{1f10a}]/u.test(
      value
    )
  ) {
    return 'La contraseña debe incluir al menos un número'
  }
  return null
}
