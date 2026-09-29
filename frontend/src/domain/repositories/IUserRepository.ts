import { IRepository } from './IRepository'
import { User, type UserWriteInput } from '../entities/User'
import { Email } from '../value-objects/Email'
import { UserRole } from '../value-objects/UserRole'

/**
 * Busqueda en el servidor del listado de usuarios (`GET /users/`). No se
 * amplia el `QueryOptions` compartido: estos filtros son solo de usuarios.
 * - `q`: 2..80 caracteres; busca en el nombre o en los digitos del telefono,
 *   nunca en el email.
 * - `email`: coincidencia exacta.
 * - `limit`: 1..500; el servidor corta ahi, asi que siempre se manda.
 */
export interface UserListQuery {
  q?: string
  email?: string
  limit: number
  includeInactive?: boolean
}

/**
 * Interfaz de repositorio específica para Usuarios.
 * Extiende de IRepository e introduce métodos especializados para la búsqueda de usuarios.
 */
/** Segundo argumento de `create`: la contraseña inicial del usuario. */
export interface IUserRepository extends IRepository<User, User, UserWriteInput, string> {
  findByEmail(email: Email): Promise<User | null>
  findByRole(role: UserRole): Promise<User[]>
  list(query: UserListQuery): Promise<User[]>
}
