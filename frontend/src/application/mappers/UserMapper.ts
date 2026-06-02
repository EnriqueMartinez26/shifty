import { User } from '../../domain/entities/User';
import type { UserResponseDTO } from '../dtos/UserDTO';

export class UserMapper {
  static toDomain(dto: UserResponseDTO): User {
    return User.fromPrimitives({
      id: dto.public_id,
      email: dto.email,
      firstName: dto.first_name,
      lastName: dto.last_name,
      phone: dto.phone,
      role: dto.role,
      isActive: dto.is_active,
      createdAt: dto.created_at,
    });
  }

  static toResponseDTO(user: User): Partial<UserResponseDTO> {
    const primitives = user.toPrimitives();
    return {
      public_id: primitives.id,
      email: primitives.email,
      first_name: primitives.firstName,
      last_name: primitives.lastName,
      role: primitives.role,
      is_active: primitives.isActive,
    };
  }
}
