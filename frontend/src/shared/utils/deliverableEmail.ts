/**
 * Espejo de `notifications/tasks.py::is_deliverable_email` del backend: el
 * alta publica inventa `{tel}@store{id}.noreply` cuando el cliente no deja
 * email. Es un dato tecnico; mostrarlo en Usuarios, Cuentas pendientes o un
 * selector de clientes confundia al dueno (QA 2026-10-02).
 */
export const isDeliverableEmail = (email: string | null | undefined): email is string =>
  !!email && email.includes('@') && !email.toLowerCase().endsWith('.noreply')

/** El email para mostrar, o null si es vacio o tecnico. */
export const displayableEmail = (email: string | null | undefined): string | null =>
  isDeliverableEmail(email) ? email : null
