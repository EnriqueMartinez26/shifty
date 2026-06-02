import { Appointment } from '../../domain/entities/Appointment';
import type { AppointmentResponseDTO } from '../dtos/BookingDTO';

export class BookingMapper {
  static toDomain(dto: AppointmentResponseDTO): Appointment {
    return Appointment.fromPrimitives(dto);
  }

  static toResponseDTO(entity: Appointment): AppointmentResponseDTO {
    return entity.toPrimitives() as AppointmentResponseDTO;
  }
}
