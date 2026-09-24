export const ROLE_SUPER_ADMIN = 'super_admin'
export const ROLE_STORE_ADMIN = 'store_admin'
export const ROLE_PROFESSIONAL = 'professional'
export const ROLE_RECEPTIONIST = 'receptionist'
// No hay `ROLE_CLIENT`: `canonicalRole` devuelve el rol crudo cuando no es uno
// de los de arriba, asi que el cliente nunca necesito su constante y nadie la
// importaba (2026-09-21).

const LEGACY_ROLE_ADMIN = 'admin'
const LEGACY_ROLE_STAFF = 'staff'

export const canonicalRole = (role: string | null | undefined, isGlobalAdmin?: boolean): string => {
  if (isGlobalAdmin) return ROLE_SUPER_ADMIN
  if (!role) return ''
  if (role === LEGACY_ROLE_ADMIN) return ROLE_STORE_ADMIN
  if (role === LEGACY_ROLE_STAFF) return ROLE_PROFESSIONAL
  return role
}

export const hasAnyRole = (
  role: string | null | undefined,
  allowedRoles: string[],
  isGlobalAdmin?: boolean
): boolean => {
  const currentRole = canonicalRole(role, isGlobalAdmin)
  return allowedRoles.includes(currentRole)
}

export const getDefaultAppRoute = (
  role: string | null | undefined,
  isGlobalAdmin?: boolean
): string => {
  const currentRole = canonicalRole(role, isGlobalAdmin)
  return currentRole === ROLE_SUPER_ADMIN ? '/control-global' : '/dashboard'
}
