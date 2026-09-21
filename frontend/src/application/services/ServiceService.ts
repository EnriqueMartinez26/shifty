import { BaseService } from './BaseService'
import {
  Service,
  type ServiceDepositMode,
  type ServiceDepositType,
  type ServiceWriteInput
} from '../../domain/entities/Service'
import type { IServiceRepository } from '../../domain/repositories/IServiceRepository'
import { Duration } from '../../domain/value-objects/Duration'
import { Price } from '../../domain/value-objects/Price'
import { ServiceColor } from '../../domain/value-objects/ServiceColor'
import apiClient from '../../infrastructure/http/client'
import { HttpServiceRepository } from '../../infrastructure/repositories/HttpServiceRepository'
import { createServiceSchema } from '../validators/service.validators'

export class ServiceService extends BaseService<Service> {
  protected repository: IServiceRepository

  constructor(serviceRepository: IServiceRepository) {
    super()
    this.repository = serviceRepository
  }

  async listServices(): Promise<Service[]> {
    return await this.execute(async () => {
      return await this.repository.findAll()
    }, 'listServices')
  }

  async createService(data: {
    name: string
    description?: string
    durationMinutes: number
    price: number
    color?: string
    imageUrl?: string
    youtubeTrailerUrl?: string
    depositMode?: ServiceDepositMode
    depositType?: ServiceDepositType
    depositAmount?: number | null
  }): Promise<Service> {
    return await this.execute(async () => {
      const validatorInput = {
        ...data,
        duration_minutes: data.durationMinutes,
        image_url: data.imageUrl,
        youtube_trailer_url: data.youtubeTrailerUrl,
        deposit_mode: data.depositMode,
        deposit_type: data.depositType,
        deposit_amount: data.depositAmount
      }

      this.validate(validatorInput, createServiceSchema)
      const validated = createServiceSchema.parse(validatorInput)

      const service = Service.create({
        name: validated.name,
        description: validated.description ?? null,
        duration: Duration.create(validated.duration_minutes),
        price: Price.create(validated.price),
        color: ServiceColor.create(validated.color || '#6366f1'),
        imageUrl: validated.image_url ?? null,
        youtubeTrailerUrl: validated.youtube_trailer_url ?? null,
        depositMode: validated.deposit_mode,
        depositType: validated.deposit_type,
        depositAmount: validated.deposit_amount ?? null,
        isActive: true
      })

      return await this.repository.create(service)
    }, 'createService')
  }

  async updateService(id: string, data: ServiceWriteInput): Promise<Service> {
    return await this.execute(async () => {
      return await this.repository.update(id, data)
    }, 'updateService')
  }

  async deleteService(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.delete(id)
    }, 'deleteService')
  }
}

export const serviceService = new ServiceService(new HttpServiceRepository(apiClient))
