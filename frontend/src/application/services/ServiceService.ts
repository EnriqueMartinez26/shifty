import { BaseService } from './BaseService';
import { Service } from '../../domain/entities/Service';
import type { IServiceRepository } from '../../domain/repositories/IServiceRepository';
import { Price } from '../../domain/value-objects/Price';
import { Duration } from '../../domain/value-objects/Duration';
import { ServiceColor } from '../../domain/value-objects/ServiceColor';
import { createServiceSchema } from '../validators/service.validators';

/**
 * Service to manage Service operations.
 * Extends BaseService<Service> to leverage template execute method, logging, and error handling.
 */
export class ServiceService extends BaseService<Service> {
  protected repository: IServiceRepository;

  /**
   * Initializes a new instance of the ServiceService.
   * 
   * @param serviceRepository The injected Service repository implementation.
   */
  constructor(serviceRepository: IServiceRepository) {
    super();
    this.repository = serviceRepository;
  }

  /**
   * Lists all services in the system.
   * 
   * @returns A promise that resolves to an array of Service entities.
   */
  async listServices(): Promise<Service[]> {
    return await this.execute(async () => {
      return await this.repository.findAll();
    }, 'listServices');
  }

  /**
   * Creates a new service with the provided details.
   * Validates input parameters before creating.
   * 
   * @param data Raw fields to build a new service.
   * @returns A promise that resolves to the created Service entity.
   */
  async createService(data: {
    name: string;
    description?: string;
    durationMinutes: number;
    price: number;
    color?: string;
    youtubeTrailerUrl?: string;
  }): Promise<Service> {
    return await this.execute(async () => {
      const validatorInput = {
        ...data,
        duration_minutes: data.durationMinutes,
        youtube_trailer_url: data.youtubeTrailerUrl,
      };

      this.validate(validatorInput, createServiceSchema);
      const validated = createServiceSchema.parse(validatorInput);

      const service = Service.create({
        name: validated.name,
        description: validated.description ?? null,
        duration: Duration.create(validated.duration_minutes),
        price: Price.create(validated.price),
        color: ServiceColor.create(validated.color || '#6366f1'),
        youtubeTrailerUrl: validated.youtube_trailer_url ?? null,
        isActive: true,
      });

      return await this.repository.create(service);
    }, 'createService');
  }

  /**
   * Updates an existing service's properties.
   * 
   * @param id Unique identifier of the service.
   * @param data Partial service properties to update.
   * @returns A promise that resolves to the updated Service entity.
   */
  async updateService(id: string, data: Partial<Service>): Promise<Service> {
    return await this.execute(async () => {
      return await this.repository.update(id, data);
    }, 'updateService');
  }

  /**
   * Deletes a service from the system by ID.
   * 
   * @param id The unique identifier of the service to delete.
   * @returns A promise resolving to void.
   */
  async deleteService(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.delete(id);
    }, 'deleteService');
  }
}
