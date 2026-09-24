import type { AxiosInstance } from 'axios'

import { BaseRepository } from './BaseRepository'
import type { ServiceResponseDTO } from '../../application/dtos/ServiceDTO'
import { ServiceMapper } from '../../application/mappers/ServiceMapper'
import { Service, type ServiceWriteInput } from '../../domain/entities/Service'
import { QueryOptions } from '../../domain/repositories/IRepository'
import type { IServiceRepository } from '../../domain/repositories/IServiceRepository'

export class HttpServiceRepository
  extends BaseRepository<Service, Service, ServiceWriteInput>
  implements IServiceRepository
{
  private client: AxiosInstance

  constructor(client: AxiosInstance) {
    super()
    this.client = client
  }

  protected async findAllImpl(_options?: QueryOptions | boolean): Promise<Service[]> {
    const { data } = await this.client.get<ServiceResponseDTO[]>('/services/')
    return data.map(ServiceMapper.toDomain)
  }

  protected async findByIdImpl(id: string): Promise<Service | null> {
    try {
      const { data } = await this.client.get<ServiceResponseDTO>(`/services/${id}`)
      return ServiceMapper.toDomain(data)
    } catch (error: unknown) {
      const maybeError = error as { response?: { status?: number } }
      if (maybeError.response?.status === 404) {
        return null
      }
      throw error
    }
  }

  protected async createImpl(service: Service): Promise<Service> {
    const { data } = await this.client.post<ServiceResponseDTO>(
      '/services/',
      ServiceMapper.toWritePayload(service)
    )
    return ServiceMapper.toDomain(data)
  }

  protected async updateImpl(id: string, service: ServiceWriteInput): Promise<Service> {
    // `toWritePayload` cubre lo que POST y PATCH comparten y omite todo campo
    // `undefined`. `is_active` se agrega aca porque solo existe en
    // `ServiceUpdate`: mandarlo en el POST seria un campo que el backend
    // descarta en silencio.
    const updateData = ServiceMapper.toWritePayload(service)
    if (service.isActive !== undefined) {
      updateData.is_active = service.isActive
    }

    const { data: responseData } = await this.client.patch<ServiceResponseDTO>(
      `/services/${id}`,
      updateData
    )
    return ServiceMapper.toDomain(responseData)
  }

  protected async deleteImpl(id: string): Promise<void> {
    await this.client.delete(`/services/${id}`)
  }
}
