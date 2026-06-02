import { Staff } from '../../domain/entities/Staff';
import type { StaffResponseDTO } from '../dtos/StaffDTO';

export class StaffMapper {
  static toDomain(dto: StaffResponseDTO): Staff {
    return Staff.fromPrimitives(dto);
  }

  static toResponseDTO(entity: Staff): StaffResponseDTO {
    return entity.toPrimitives();
  }
}
