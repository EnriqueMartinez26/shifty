import { IRepository } from './IRepository'
import { User, type UserWriteInput } from '../entities/User'
import { Email } from '../value-objects/Email'
import { UserRole } from '../value-objects/UserRole'

/**
 * Interfaz de repositorio específica para Usuarios.
 * Extiende de IRepository e introduce métodos especializados para la búsqueda de usuarios.
 */
/** Segundo argumento de `create`: la contraseña inicial del usuario. */
export interface IUserRepository extends IRepository<User, User, UserWriteInput, string> {
  findByEmail(email: Email): Promise<User | null>
  findByRole(role: UserRole): Promise<User[]>
}
