/**
 * Espejo de `core/validation.py::validate_password_strength` para avisar antes
 * de enviar: al menos 12 caracteres, una letra y un numero. La denylist de
 * claves comunes vive solo en el backend; su 422 se mapea al mismo texto.
 */
export const PASSWORD_POLICY_TEXT =
  'La contraseña tiene que tener al menos 12 caracteres, con letras y números, y no ser una contraseña común.'

export const passwordPolicyError = (password: string): string | null => {
  const ok = password.length >= 12 && /\p{L}/u.test(password) && /\d/.test(password)
  return ok ? null : PASSWORD_POLICY_TEXT
}
