import type { AxiosInstance } from 'axios'
import { BaseRepository } from './BaseRepository'
import { IUserRepository } from '../../domain/repositories/IUserRepository'
import { User } from '../../domain/entities/User'
import { Email } from '../../domain/value-objects/Email'
import { UserRole } from '../../domain/value-objects/UserRole'
import { QueryOptions } from '../../domain/repositories/IRepository'
import { UserResponseDTO } from '../../application/dtos/UserDTO'
import { UserMapper } from '../../application/mappers/UserMapper'

/**
 * Implementación HTTP concreta para la persistencia de usuarios.
 * Extiende de BaseRepository para beneficiarse del control de errores unificado.
 */
export class HttpUserRepository
  extends BaseRepository<User, User, Partial<User>>
  implements IUserRepository
{
  private client: AxiosInstance

  constructor(client: AxiosInstance) {
    super()
    this.client = client
  }

  // --- Métodos Específicos de IUserRepository ---

  public async findByEmail(email: Email): Promise<User | null> {
    try {
      const { data } = await this.client.get<UserResponseDTO[]>(`/users/?email=${email.getValue()}`)
      return data.length > 0 ? UserMapper.toDomain(data[0]) : null
    } catch (error) {
      this.handleRepositoryError('findByEmail', error)
    }
  }

  public async findByRole(role: UserRole): Promise<User[]> {
    try {
      const { data } = await this.client.get<UserResponseDTO[]>(`/users/?role=${role.getValue()}`)
      return data.map(UserMapper.toDomain)
    } catch (error) {
      this.handleRepositoryError('findByRole', error)
    }
  }

  // --- Implementación de Hooks Abstractos (Template Method Pattern) ---

  protected async findAllImpl(options?: QueryOptions | boolean): Promise<User[]> {
    let includeInactive = false
    if (typeof options === 'boolean') {
      includeInactive = options
    } else if (options && typeof options === 'object') {
      includeInactive = !!options.includeInactive
    }

    const { data } = await this.client.get<UserResponseDTO[]>(
      `/users/?include_inactive=${includeInactive}`
    )
    return data.map(UserMapper.toDomain)
  }

  protected async findByIdImpl(id: string): Promise<User | null> {
    try {
      const { data } = await this.client.get<UserResponseDTO>(`/users/${id}`)
      return UserMapper.toDomain(data)
    } catch (error: any) {
      if (error.response?.status === 404) {
        return null
      }
      throw error
    }
  }

  protected async createImpl(user: User, password?: string): Promise<User> {
    const primitives = user.toPrimitives()
    const { data } = await this.client.post<UserResponseDTO>('/users/', {
      email: primitives.email,
      password: password,
      first_name: primitives.firstName,
      last_name: primitives.lastName,
      phone: primitives.phone,
      role: primitives.role
    })
    return UserMapper.toDomain(data)
  }

  protected async updateImpl(id: string, data: Partial<User>): Promise<User> {
    const updateData: any = {}
    if (data.firstName !== undefined) updateData.first_name = data.firstName
    if (data.lastName !== undefined) updateData.last_name = data.lastName
    if (data.phone !== undefined) updateData.phone = data.phone
    if (data.role !== undefined) updateData.role = data.role
    if (data.isActive !== undefined) updateData.is_active = data.isActive

    const { data: responseData } = await this.client.patch<UserResponseDTO>(
      `/users/${id}`,
      updateData
    )
    return UserMapper.toDomain(responseData)
  }

  protected async deleteImpl(id: string): Promise<void> {
    await this.client.delete(`/users/${id}`)
  }
}
export default HttpUserRepository
