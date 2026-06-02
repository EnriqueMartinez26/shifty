import { BaseRepository } from './BaseRepository';
import { IUserRepository } from '../../domain/repositories/IUserRepository';
import { User } from '../../domain/entities/User';
import { Email } from '../../domain/value-objects/Email';
import { UserRole } from '../../domain/value-objects/UserRole';
import { QueryOptions } from '../../domain/repositories/IRepository';
import { NotFoundError } from '../../shared/errors/NotFoundError';

/**
 * Implementación InMemory concreta para la persistencia de usuarios.
 * Mantiene un almacenamiento local Map ideal para pruebas rápidas y robustas.
 */
export class InMemoryUserRepository 
  extends BaseRepository<User, User, Partial<User>> 
  implements IUserRepository 
{
  private store: Map<string, User> = new Map();

  // --- Métodos Específicos de IUserRepository ---

  public async findByEmail(email: Email): Promise<User | null> {
    for (const user of this.store.values()) {
      if (user.toPrimitives().email === email.getValue()) {
        return user;
      }
    }
    return null;
  }

  public async findByRole(role: UserRole): Promise<User[]> {
    const result: User[] = [];
    for (const user of this.store.values()) {
      if (user.toPrimitives().role === role.getValue()) {
        result.push(user);
      }
    }
    return result;
  }

  // --- Implementación de Hooks Abstractos (Template Method Pattern) ---

  protected async findAllImpl(options?: QueryOptions | boolean): Promise<User[]> {
    let includeInactive = false;
    if (typeof options === 'boolean') {
      includeInactive = options;
    } else if (options && typeof options === 'object') {
      includeInactive = !!options.includeInactive;
    }

    let users = Array.from(this.store.values());
    if (!includeInactive) {
      users = users.filter(u => u.isActive);
    }
    return users;
  }

  protected async findByIdImpl(id: string): Promise<User | null> {
    return this.store.get(id) || null;
  }

  protected async createImpl(user: User, _password?: string): Promise<User> {
    this.store.set(user.id, user);
    return user;
  }

  protected async updateImpl(id: string, data: Partial<User>): Promise<User> {
    const existing = this.store.get(id);
    if (!existing) {
      throw new NotFoundError(`User with id ${id} not found`);
    }

    const updatedUser = User.fromPrimitives({
      id: existing.id,
      email: data.email ? data.email.getValue() : existing.email.getValue(),
      firstName: data.firstName !== undefined ? data.firstName : existing.firstName,
      lastName: data.lastName !== undefined ? data.lastName : existing.lastName,
      phone: data.phone !== undefined ? data.phone : existing.phone,
      role: data.role ? data.role.getValue() : existing.role.getValue(),
      isActive: data.isActive !== undefined ? data.isActive : existing.isActive,
      createdAt: existing.toPrimitives().createdAt
    });

    this.store.set(id, updatedUser);
    return updatedUser;
  }

  protected async deleteImpl(id: string): Promise<void> {
    if (!this.store.has(id)) {
      throw new NotFoundError(`User with id ${id} not found`);
    }
    this.store.delete(id);
  }

  /**
   * Limpia todo el almacén de datos (helper de testing).
   */
  public clear(): void {
    this.store.clear();
  }
}
export default InMemoryUserRepository;
