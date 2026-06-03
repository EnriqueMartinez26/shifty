import { Service } from "../../domain/entities/Service";
import type { ServiceResponseDTO } from "../dtos/ServiceDTO";

export class ServiceMapper {
  static toDomain(dto: ServiceResponseDTO): Service {
    return Service.fromPrimitives({
      id: dto.public_id,
      name: dto.name,
      description: dto.description,
      duration_minutes: dto.duration_minutes,
      price: dto.price,
      color: dto.color,
      image_url: dto.image_url,
      youtube_trailer_url: dto.youtube_trailer_url,
      is_active: dto.is_active,
    });
  }

  static toResponseDTO(service: Service): ServiceResponseDTO {
    const primitives = service.toPrimitives();
    return {
      public_id: primitives.id,
      name: primitives.name,
      description: primitives.description,
      duration_minutes: primitives.duration_minutes,
      price: primitives.price,
      color: primitives.color,
      image_url: primitives.image_url,
      youtube_trailer_url: primitives.youtube_trailer_url,
      is_active: primitives.is_active,
    };
  }
}
