import { Staff } from '../../domain/entities/Staff'
import type { StaffResponseDTO } from '../dtos/StaffDTO'

export class StaffMapper {
  static toDomain(dto: StaffResponseDTO): Staff {
    return Staff.fromPrimitives(dto)
  }

  static toResponseDTO(entity: Staff): StaffResponseDTO {
    return entity.toPrimitives()
  }

  /**
   * Payload de escritura hacia la API. Un recurso (cancha, sala) no tiene
   * nombre ni email: mandarlos vacios hacia `StaffUpdate`, que exige
   * `min_length=1`, devolvia 422 y ningun recurso se podia editar nunca.
   */
  static toWritePayload(entity: Staff): Record<string, unknown> {
    const primitives = entity.toPrimitives()
    if (!entity.isResource) return primitives
    const sinContacto: Record<string, unknown> = { ...primitives }
    delete sinContacto.first_name
    delete sinContacto.last_name
    delete sinContacto.email
    return sinContacto
  }
}
