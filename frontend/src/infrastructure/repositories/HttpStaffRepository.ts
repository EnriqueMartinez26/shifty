import type { AxiosInstance } from 'axios'
import { Staff } from '../../domain/entities/Staff'
import { BaseRepository } from './BaseRepository'
import type { IStaffRepository } from '../../domain/repositories/IStaffRepository'
import type { StaffResponseDTO } from '../../application/dtos/StaffDTO'
import { StaffMapper } from '../../application/mappers/StaffMapper'
import { QueryOptions } from '../../domain/repositories/IRepository'

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
    } catch (error: any) {
      if (error.response?.status === 404) {
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
