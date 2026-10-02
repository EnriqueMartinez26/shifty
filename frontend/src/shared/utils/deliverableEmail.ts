/**
 * Espejo de `notifications/tasks.py::is_deliverable_email` del backend: el
 * alta publica inventa `{tel}@store{id}.noreply` cuando el cliente no deja
 * email. Es un dato tecnico; mostrarlo en Usuarios, Cuentas pendientes o un
 * selector de clientes confundia al dueno (QA 2026-10-02).
 */
export const isDeliverableEmail = (email: string | null | undefined): email is string =>
  !!email && email.includes('@') && !email.toLowerCase().endsWith('.noreply')

/** Si el texto es un email tecnico (`.noreply`). */
const isTechnicalEmail = (value: string | null | undefined): boolean =>
  !!value && value.includes('@') && value.toLowerCase().endsWith('.noreply')

/**
 * Un nombre que el backend armo con el email tecnico (sin nombre ni apellido
 * cae al email: ledger/router.py::_client_display_name) se cambia por el
 * respaldo; cualquier otro texto queda igual.
 */
export const withoutTechnicalEmail = (value: string, fallback: string): string =>
  isTechnicalEmail(value) ? fallback : value

/** El email para mostrar, o null si es vacio o tecnico. */
export const displayableEmail = (email: string | null | undefined): string | null =>
  isDeliverableEmail(email) ? email : null
