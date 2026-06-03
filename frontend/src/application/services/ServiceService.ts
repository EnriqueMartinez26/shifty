import { BaseService } from "./BaseService";
import { Service } from "../../domain/entities/Service";
import type { IServiceRepository } from "../../domain/repositories/IServiceRepository";
import { Price } from "../../domain/value-objects/Price";
import { Duration } from "../../domain/value-objects/Duration";
import { ServiceColor } from "../../domain/value-objects/ServiceColor";
import { createServiceSchema } from "../validators/service.validators";

export class ServiceService extends BaseService<Service> {
  protected repository: IServiceRepository;

  constructor(serviceRepository: IServiceRepository) {
    super();
    this.repository = serviceRepository;
  }

  async listServices(): Promise<Service[]> {
    return await this.execute(async () => {
      return await this.repository.findAll();
    }, "listServices");
  }

  async createService(data: {
    name: string;
    description?: string;
    durationMinutes: number;
    price: number;
    color?: string;
    imageUrl?: string;
    youtubeTrailerUrl?: string;
  }): Promise<Service> {
    return await this.execute(async () => {
      const validatorInput = {
        ...data,
        duration_minutes: data.durationMinutes,
        image_url: data.imageUrl,
        youtube_trailer_url: data.youtubeTrailerUrl,
      };

      this.validate(validatorInput, createServiceSchema);
      const validated = createServiceSchema.parse(validatorInput);

      const service = Service.create({
        name: validated.name,
        description: validated.description ?? null,
        duration: Duration.create(validated.duration_minutes),
        price: Price.create(validated.price),
        color: ServiceColor.create(validated.color || "#6366f1"),
        imageUrl: validated.image_url ?? null,
        youtubeTrailerUrl: validated.youtube_trailer_url ?? null,
        isActive: true,
      });

      return await this.repository.create(service);
    }, "createService");
  }

  async updateService(id: string, data: Partial<Service>): Promise<Service> {
    return await this.execute(async () => {
      return await this.repository.update(id, data);
    }, "updateService");
  }

  async deleteService(id: string): Promise<void> {
    await this.execute(async () => {
      await this.repository.delete(id);
    }, "deleteService");
  }
}
