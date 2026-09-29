import type { User } from '@domain/entities/User'

import type { AuthenticatedUser } from '@application/services/AuthService'

type Viewer = Pick<AuthenticatedUser, 'public_id' | 'is_global_admin'> | null

/** Que puede tocar quien mira la pantalla en el formulario de un usuario. */
export interface UserFormRules {
  /** Ofrecer "Administrador" en el selector de rol. */
  showAdminOption: boolean
  canChangeRole: boolean
  canChangePassword: boolean
}

/**
 * Espejo de las guardas del backend (`core/roles.py`), para no ofrecer lo que
 * va a responder 403 (FF-09). La garantia sigue siendo el backend; esto solo
 * evita el viaje:
 * - Solo el superadmin otorga `admin` (`assert_can_grant_role`, regla 16). Si
 *   el editado ya es admin la opcion se muestra para que el selector refleje
 *   su rol; reenviar el mismo rol no es otorgarlo.
 * - Un admin de tienda no cambia rol ni clave de OTRO admin
 *   (`assert_can_change_access`, S-15).
 * - La propia clave se cambia por /auth/change-password
 *   (`SELF_PASSWORD_CHANGE_DENIED`), y el propio rol no se toca desde aca.
 *
 * El superadmin sale de `useAuth()` (quien mira), nunca del User de dominio.
 */
export const userFormRules = (viewer: Viewer, target: User | null): UserFormRules => {
  const isSuperadmin = Boolean(viewer?.is_global_admin)
  if (!target) {
    return { showAdminOption: isSuperadmin, canChangeRole: true, canChangePassword: true }
  }
  const isSelf = viewer?.public_id === target.id
  const targetIsAdmin = target.role.isAdmin()
  const canChangeAccess = !isSelf && (isSuperadmin || !targetIsAdmin)
  return {
    showAdminOption: isSuperadmin || targetIsAdmin,
    canChangeRole: canChangeAccess,
    canChangePassword: canChangeAccess
  }
}

/**
 * La baja es una desactivacion (`DELETE /users/{id}` hace soft delete). No se
 * ofrece sobre uno mismo (`SELF_DEACTIVATION_DENIED`), sobre otro admin si
 * quien mira no es superadmin (S-15), ni sobre alguien ya inactivo.
 */
export const canDeactivateUser = (viewer: Viewer, target: User): boolean => {
  if (!target.isActive || viewer?.public_id === target.id) return false
  return Boolean(viewer?.is_global_admin) || !target.role.isAdmin()
}
