import type { AuthenticatedUser, CurrentUserDTO } from '../dtos/CurrentUserDTO'

// Un nombre vacio o en blanco es "sin nombre": nunca se propone como nombre
// visible. `?.` cubre tambien un backend anterior que no mandaba el campo.
const optionalName = (value: string | null | undefined): string | undefined => {
  const trimmed = value?.trim()
  return trimmed ? trimmed : undefined
}

/**
 * `/me` a la sesion del panel. Desde 2026-10-14 trae nombre y apellido (leidos
 * de la base, no del token): sin ellos "Agregarme como profesional" no podia
 * proponer el nombre visible.
 */
export const toSessionUser = (dto: CurrentUserDTO): AuthenticatedUser => ({
  email: dto.email,
  role: dto.role,
  store_id: dto.store_id,
  public_id: dto.public_id,
  is_global_admin: dto.is_global_admin,
  first_name: optionalName(dto.first_name),
  last_name: optionalName(dto.last_name)
})
