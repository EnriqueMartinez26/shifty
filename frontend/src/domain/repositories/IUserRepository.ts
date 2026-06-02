import { User } from '../entities/User';
import { IRepository } from './IRepository';
import { Email } from '../value-objects/Email';
import { UserRole } from '../value-objects/UserRole';

/**
 * Interfaz de repositorio específica para Usuarios.
 * Extiende de IRepository e introduce métodos especializados para la búsqueda de usuarios.
 */
export interface IUserRepository extends IRepository<User, User, Partial<User>> {
  findByEmail(email: Email): Promise<User | null>;
  findByRole(role: UserRole): Promise<User[]>;
}
export default IUserRepository;
