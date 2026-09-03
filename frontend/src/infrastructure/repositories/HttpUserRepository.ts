import type { AxiosInstance } from 'axios'

import { BaseRepository } from './BaseRepository'
import { UserResponseDTO } from '../../application/dtos/UserDTO'
import { UserMapper } from '../../application/mappers/UserMapper'
import { User } from '../../domain/entities/User'
import { QueryOptions } from '../../domain/repositories/IRepository'
import { IUserRepository } from '../../domain/repositories/IUserRepository'
import { Email } from '../../domain/value-objects/Email'
import { UserRole } from '../../domain/value-objects/UserRole'

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
      const first = data[0]
      return first ? UserMapper.toDomain(first) : null
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
      includeInactive = Boolean(options.includeInactive)
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
    } catch (error: unknown) {
      const maybeError = error as { response?: { status?: number } }
      if (maybeError.response?.status === 404) {
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
    // El formulario envia snake_case (first_name, password), pero antes esto
    // solo leia camelCase (data.firstName) y NO manejaba password: editar el
    // nombre o la clave de un usuario se descartaba en silencio. Se aceptan
    // ambas convenciones y se incluye password (solo si no viene vacio).
    const raw = data as unknown as Record<string, unknown>
    const updateData: Record<string, unknown> = {}
    const firstName = raw.firstName ?? raw.first_name
    if (firstName !== undefined) updateData.first_name = firstName
    const lastName = raw.lastName ?? raw.last_name
    if (lastName !== undefined) updateData.last_name = lastName
    if (raw.phone !== undefined) updateData.phone = raw.phone
    if (raw.role !== undefined) updateData.role = raw.role
    const isActive = raw.isActive ?? raw.is_active
    if (isActive !== undefined) updateData.is_active = isActive
    const password = raw.password
    if (typeof password === 'string' && password.length > 0) {
      updateData.password = password
    }

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
