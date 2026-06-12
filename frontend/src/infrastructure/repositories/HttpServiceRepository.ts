import type { AxiosInstance } from 'axios'
import { Service } from '../../domain/entities/Service'
import { BaseRepository } from './BaseRepository'
import type { IServiceRepository } from '../../domain/repositories/IServiceRepository'
import type { ServiceResponseDTO } from '../../application/dtos/ServiceDTO'
import { ServiceMapper } from '../../application/mappers/ServiceMapper'
import { QueryOptions } from '../../domain/repositories/IRepository'

export class HttpServiceRepository
  extends BaseRepository<Service, Service, Partial<Service>>
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
    } catch (error: any) {
      if (error.response?.status === 404) {
        return null
      }
      throw error
    }
  }

  protected async createImpl(service: Service): Promise<Service> {
    const primitives = service.toPrimitives()
    const { data } = await this.client.post<ServiceResponseDTO>('/services/', {
      name: primitives.name,
      description: primitives.description,
      duration_minutes: primitives.duration_minutes,
      price: primitives.price,
      color: primitives.color,
      image_url: primitives.image_url,
      youtube_trailer_url: primitives.youtube_trailer_url
    })
    return ServiceMapper.toDomain(data)
  }

  protected async updateImpl(id: string, service: Partial<Service>): Promise<Service> {
    const updateData: any = {}
    const serviceData = service as any

    if (serviceData.name !== undefined) updateData.name = serviceData.name
    if (serviceData.description !== undefined) updateData.description = serviceData.description
    if (serviceData.durationMinutes !== undefined) {
      updateData.duration_minutes = serviceData.durationMinutes
    } else if (serviceData.duration !== undefined) {
      updateData.duration_minutes = serviceData.duration.getValue()
    }
    if (serviceData.price !== undefined) {
      updateData.price =
        typeof serviceData.price === 'number' ? serviceData.price : serviceData.price.getValue()
    }
    if (serviceData.color !== undefined) {
      updateData.color = serviceData.color
    }
    if (serviceData.imageUrl !== undefined) {
      updateData.image_url = serviceData.imageUrl
    }
    if (serviceData.image_url !== undefined) {
      updateData.image_url = serviceData.image_url
    }
    if (serviceData.youtubeTrailerUrl !== undefined) {
      updateData.youtube_trailer_url = serviceData.youtubeTrailerUrl
    }
    if (serviceData.youtube_trailer_url !== undefined) {
      updateData.youtube_trailer_url = serviceData.youtube_trailer_url
    }
    if (serviceData.isActive !== undefined) {
      updateData.is_active = serviceData.isActive
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

export default HttpServiceRepository
