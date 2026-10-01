import type { AxiosInstance } from 'axios'

import { BaseRepository } from './BaseRepository'
import type { ServiceResponseDTO } from '../../application/dtos/ServiceDTO'
import { ServiceMapper } from '../../application/mappers/ServiceMapper'
import { Service, type ServiceWriteInput } from '../../domain/entities/Service'
import { QueryOptions } from '../../domain/repositories/IRepository'
import type { IServiceRepository } from '../../domain/repositories/IServiceRepository'
import { NotFoundError } from '../../shared/errors/NotFoundError'

export class HttpServiceRepository
  extends BaseRepository<Service, Service, ServiceWriteInput>
  implements IServiceRepository
{
  private client: AxiosInstance

  constructor(client: AxiosInstance) {
    super()
    this.client = client
  }

  protected async findAllImpl(options?: QueryOptions | boolean): Promise<Service[]> {
    const includeInactive =
      typeof options === 'boolean' ? options : Boolean(options?.includeInactive)
    // `include_inactive` exige STORE_MANAGERS en el backend: a un profesional
    // le da 403. Por eso viaja solo cuando se pide (el catalogo del panel) y la
    // lista compartida sale sin parametros (FF-22).
    const { data } = includeInactive
      ? await this.client.get<ServiceResponseDTO[]>('/services/', {
          params: { include_inactive: true }
        })
      : await this.client.get<ServiceResponseDTO[]>('/services/')
    return data.map(ServiceMapper.toDomain)
  }

  protected async findByIdImpl(id: string): Promise<Service | null> {
    try {
      const { data } = await this.client.get<ServiceResponseDTO>(`/services/${id}`)
      return ServiceMapper.toDomain(data)
    } catch (error: unknown) {
      // El cliente HTTP ya normalizo el 404 (FF-35): no trae `response`.
      if (error instanceof NotFoundError) return null
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
