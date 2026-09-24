import { BaseService } from './BaseService'
import { User, type UserWriteInput } from '../../domain/entities/User'
import type { IUserRepository } from '../../domain/repositories/IUserRepository'
import { CreateUserUseCase } from '../../domain/use-cases/user/CreateUserUseCase'
import type { CreateUserInput } from '../../domain/use-cases/user/CreateUserUseCase'
import { UserRole } from '../../domain/value-objects/UserRole'
import apiClient from '../../infrastructure/http/client'
import { HttpUserRepository } from '../../infrastructure/repositories/HttpUserRepository'
import { createUserSchema } from '../validators/user.validators'

/**
 * Service to manage User operations.
 * Extends BaseService<User> to leverage template execute method, logging, and error handling.
 */
export class UserService extends BaseService<User> {
  protected repository: IUserRepository
  private createUserUseCase: CreateUserUseCase

  /**
   * Initializes a new instance of the UserService.
   *
   * @param userRepository The injected User repository implementation.
   */
  constructor(userRepository: IUserRepository) {
    super()
    this.repository = userRepository
    this.createUserUseCase = new CreateUserUseCase(userRepository)
  }

  /**
   * Creates a new user in the system after validating inputs.
   *
   * @param input Raw user registration input.
   * @returns A promise that resolves to the created User entity.
   */
  async createUser(input: CreateUserInput): Promise<User> {
    return await this.execute(async () => {
      // El schema valida en snake_case; el llamador (UserManagementContainer)
      // ya mapea el formulario a CreateUserInput, sin cast en el medio.
      const validatorInput = {
        ...input,
        first_name: input.firstName,
        last_name: input.lastName
      }

      this.validate(validatorInput, createUserSchema)
      const validated = createUserSchema.parse(validatorInput)

      return await this.createUserUseCase.execute({
        ...validated,
        firstName: validated.first_name,
        lastName: validated.last_name
      })
    }, 'createUser')
  }

  /**
   * Lists all users in the system.
   *
   * @param includeInactive Whether to include deactivated users.
   * @returns A promise that resolves to an array of User entities.
   */
  async listUsers(includeInactive?: boolean): Promise<User[]> {
    return await this.execute(async () => {
      return await this.repository.findAll(includeInactive)
    }, 'listUsers')
  }

  /**
   * Lists the store's active clients (GET /users/?role=client; the backend
   * leaves out inactive users by default).
   */
  async listClients(): Promise<User[]> {
    return await this.execute(
      () => this.repository.findByRole(UserRole.create('client')),
      'listClients'
    )
  }

  /**
   * Hard-deletes a user from the system by ID.
   *
   * @param id The unique identifier of the user to delete.
   * @returns A promise resolving to void.
   */
  async deleteUser(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.delete(id)
    }, 'deleteUser')
  }

  /**
   * Updates partial data of a user.
   *
   * @param id The unique identifier of the user to update.
   * @param data The fields to write; only the ones present are sent.
   * @returns A promise that resolves to the updated User entity.
   */
  async updateUser(id: string, data: UserWriteInput): Promise<User> {
    return await this.execute(async () => {
      return await this.repository.update(id, data)
    }, 'updateUser')
  }
}

export const userService = new UserService(new HttpUserRepository(apiClient))
