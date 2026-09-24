import type { AxiosInstance } from 'axios'

import { BaseRepository } from './BaseRepository'
import { UserResponseDTO } from '../../application/dtos/UserDTO'
import { UserMapper } from '../../application/mappers/UserMapper'
import { User, type UserWriteInput } from '../../domain/entities/User'
import { QueryOptions } from '../../domain/repositories/IRepository'
import { IUserRepository } from '../../domain/repositories/IUserRepository'
import { Email } from '../../domain/value-objects/Email'
import { UserRole } from '../../domain/value-objects/UserRole'

type UserPayloadInput = {
  [K in keyof UserWriteInput]?: UserWriteInput[K] | null
} & { email?: string }

const SNAKE_CASE_FIELDS: Record<keyof UserPayloadInput, string> = {
  email: 'email',
  password: 'password',
  firstName: 'first_name',
  lastName: 'last_name',
  phone: 'phone',
  role: 'role',
  isActive: 'is_active'
}

/**
 * Unico mapeo del payload de escritura de usuarios (POST y PATCH): solo viajan
 * los campos PRESENTES, en snake_case, y `password` vacio nunca viaja (editar
 * sin tocar la clave no la cambia; crear sin clave lo rechaza el backend).
 */
const toUserPayload = (input: UserPayloadInput): Record<string, unknown> => {
  const payload: Record<string, unknown> = {}
  for (const key of Object.keys(SNAKE_CASE_FIELDS) as (keyof UserPayloadInput)[]) {
    const value = input[key]
    if (value === undefined) continue
    if (key === 'password' && !value) continue
    payload[SNAKE_CASE_FIELDS[key]] = value
  }
  return payload
}

/**
 * Implementación HTTP concreta para la persistencia de usuarios.
 * Extiende de BaseRepository para beneficiarse del control de errores unificado.
 */
export class HttpUserRepository
  extends BaseRepository<User, User, UserWriteInput>
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
    const { data } = await this.client.post<UserResponseDTO>(
      '/users/',
      toUserPayload({
        email: primitives.email,
        password,
        firstName: primitives.firstName,
        lastName: primitives.lastName,
        phone: primitives.phone,
        role: primitives.role
      })
    )
    return UserMapper.toDomain(data)
  }

  protected async updateImpl(id: string, data: UserWriteInput): Promise<User> {
    const { data: responseData } = await this.client.patch<UserResponseDTO>(
      `/users/${id}`,
      toUserPayload(data)
    )
    return UserMapper.toDomain(responseData)
  }

  protected async deleteImpl(id: string): Promise<void> {
    await this.client.delete(`/users/${id}`)
  }
}
