import type { AxiosInstance } from 'axios'

import { BaseRepository } from './BaseRepository'
import type { StaffResponseDTO } from '../../application/dtos/StaffDTO'
import { StaffMapper } from '../../application/mappers/StaffMapper'
import { Staff } from '../../domain/entities/Staff'
import { QueryOptions } from '../../domain/repositories/IRepository'
import type { IStaffRepository } from '../../domain/repositories/IStaffRepository'

export class HttpStaffRepository
  extends BaseRepository<Staff, Staff, Staff>
  implements IStaffRepository
{
  private client: AxiosInstance

  constructor(client: AxiosInstance) {
    super()
    this.client = client
  }

  protected async findAllImpl(_options?: QueryOptions | boolean): Promise<Staff[]> {
    const { data } = await this.client.get<StaffResponseDTO[]>('/staff/')
    return data.map(StaffMapper.toDomain)
  }

  protected async findByIdImpl(id: string): Promise<Staff | null> {
    try {
      const { data } = await this.client.get<StaffResponseDTO>(`/staff/${id}`)
      return StaffMapper.toDomain(data)
    } catch (error: unknown) {
      const maybeError = error as { response?: { status?: number } }
      if (maybeError.response?.status === 404) {
        return null
      }
      throw error
    }
  }

  protected async createImpl(staff: Staff): Promise<Staff> {
    const payload = StaffMapper.toResponseDTO(staff)
    const { data } = await this.client.post<StaffResponseDTO>('/staff/', payload)
    return StaffMapper.toDomain(data)
  }

  protected async updateImpl(id: string, staff: Staff): Promise<Staff> {
    const payload = StaffMapper.toResponseDTO(staff)
    const { data } = await this.client.put<StaffResponseDTO>(`/staff/${id}`, payload)
    return StaffMapper.toDomain(data)
  }

  protected async deleteImpl(id: string): Promise<void> {
    await this.client.delete(`/staff/${id}`)
  }
}
export default HttpStaffRepository
