import { Staff, type StaffWriteInput } from '../../domain/entities/Staff'
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

  /** Payload parcial de `StaffUpdate`: solo viaja lo que el llamador definio. */
  static toUpdatePayload(input: StaffWriteInput): Record<string, unknown> {
    const fields: Record<string, unknown> = {
      first_name: input.firstName,
      last_name: input.lastName,
      email: input.email,
      display_name: input.displayName,
      service_ids: input.serviceIds
    }
    return Object.fromEntries(Object.entries(fields).filter(([, value]) => value !== undefined))
  }
}
