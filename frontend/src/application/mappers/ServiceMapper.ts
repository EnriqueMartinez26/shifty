import { Service, type ServiceWriteInput } from '../../domain/entities/Service'
import type { ServiceResponseDTO } from '../dtos/ServiceDTO'

/**
 * Copia el campo solo si tiene un valor DEFINIDO. `null` cuenta como definido
 * (es "borrame este campo"); `undefined` es "no lo menciones".
 */
const assignDefined = (target: Record<string, unknown>, key: string, value: unknown): void => {
  if (value !== undefined) {
    target[key] = value
  }
}

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
      deposit_mode: dto.deposit_mode,
      deposit_type: dto.deposit_type,
      deposit_amount: dto.deposit_amount,
      is_active: dto.is_active
    })
  }

  static toResponseDTO(service: Service): ServiceResponseDTO {
    const primitives = service.toPrimitives()
    return {
      public_id: primitives.id,
      name: primitives.name,
      description: primitives.description,
      duration_minutes: primitives.duration_minutes,
      price: primitives.price,
      color: primitives.color,
      image_url: primitives.image_url,
      youtube_trailer_url: primitives.youtube_trailer_url,
      deposit_mode: primitives.deposit_mode,
      deposit_type: primitives.deposit_type,
      deposit_amount: primitives.deposit_amount,
      is_active: primitives.is_active
    }
  }

  /**
   * Payload de escritura hacia la API, unico para POST y PATCH. Cubre los
   * campos que `ServiceCreate` y `ServiceUpdate` comparten; `is_active` queda
   * afuera porque solo existe en `ServiceUpdate` y lo agrega el repositorio.
   *
   * Regla que sostiene el dinero: un campo `undefined` NO se manda. Mandar
   * `deposit_mode: 'none'` por omision apagaria una sena configurada, y la
   * tienda dejaria de cobrarla sin que nadie lo pidiera.
   */
  static toWritePayload(source: ServiceWriteInput): Record<string, unknown> {
    const payload: Record<string, unknown> = {}

    assignDefined(payload, 'name', source.name)
    assignDefined(payload, 'description', source.description)
    assignDefined(
      payload,
      'duration_minutes',
      source.durationMinutes ?? source.duration?.getValue()
    )
    assignDefined(
      payload,
      'price',
      typeof source.price === 'number' ? source.price : source.price?.getValue()
    )
    assignDefined(payload, 'color', source.color)
    assignDefined(payload, 'image_url', source.imageUrl)
    assignDefined(payload, 'youtube_trailer_url', source.youtubeTrailerUrl)
    assignDefined(payload, 'deposit_mode', source.depositMode)
    assignDefined(payload, 'deposit_type', source.depositType)
    assignDefined(payload, 'deposit_amount', source.depositAmount)

    return payload
  }
}
