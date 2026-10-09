import { UserMapper } from './UserMapper'
import type { UserResponseDTO } from '../dtos/UserDTO'

// Cobertura de F9-08 (2026-09-30): el mapper no tenia test propio. Tests solo
// de cobertura, verdes desde el principio: describen el comportamiento actual.

const dto: UserResponseDTO = {
  public_id: '01J8ZQ4Y7XKQ3M0B5N6P7R8S9T',
  email: 'ana@example.com',
  first_name: 'Ana',
  last_name: 'Perez',
  phone: '+5491100000000',
  role: 'receptionist',
  is_active: true,
  is_global_admin: false,
  created_at: '2026-09-10T12:00:00.000Z',
  updated_at: '2026-09-11T12:00:00.000Z'
}

describe('UserMapper.toDomain', () => {
  it('mapea cada campo del DTO a la entidad', () => {
    const user = UserMapper.toDomain(dto)

    expect(user.toPrimitives()).toEqual({
      id: dto.public_id,
      email: 'ana@example.com',
      firstName: 'Ana',
      lastName: 'Perez',
      phone: '+5491100000000',
      role: 'receptionist',
      isActive: true,
      createdAt: '2026-09-10T12:00:00.000Z'
    })
  })

  it('conserva los null de nombre, apellido y telefono', () => {
    const user = UserMapper.toDomain({ ...dto, first_name: null, last_name: null, phone: null })

    expect(user.firstName).toBeNull()
    expect(user.lastName).toBeNull()
    expect(user.phone).toBeNull()
    expect(user.fullName).toBe('Sin Nombre')
  })

  it('normaliza el email a minusculas (value object Email)', () => {
    expect(UserMapper.toDomain({ ...dto, email: ' Ana@Example.COM ' }).email.getValue()).toBe(
      'ana@example.com'
    )
  })

  it('un rol que el front no conoce lanza INVALID_ROLE', () => {
    const conRolAjeno = { ...dto, role: 'superadmin' } as unknown as UserResponseDTO

    expect(() => UserMapper.toDomain(conRolAjeno)).toThrow(
      expect.objectContaining({ code: 'INVALID_ROLE' })
    )
  })
})

describe('UserMapper ida y vuelta', () => {
  it('DTO -> entidad -> DTO conserva los campos que el mapper devuelve', () => {
    const vuelta = UserMapper.toResponseDTO(UserMapper.toDomain(dto))

    expect(vuelta).toEqual({
      public_id: dto.public_id,
      email: dto.email,
      first_name: dto.first_name,
      last_name: dto.last_name,
      role: dto.role,
      is_active: dto.is_active
    })
  })

  it('la vuelta es parcial: phone y las fechas no vuelven al DTO', () => {
    // Comportamiento actual: toResponseDTO devuelve Partial<UserResponseDTO>
    // y no tiene consumidores en src (solo lo usa este test).
    const vuelta = UserMapper.toResponseDTO(UserMapper.toDomain(dto))

    expect(vuelta).not.toHaveProperty('phone')
    expect(vuelta).not.toHaveProperty('created_at')
    expect(vuelta).not.toHaveProperty('updated_at')
    expect(vuelta).not.toHaveProperty('is_global_admin')
  })

  it('los null de nombre y apellido vuelven como null', () => {
    const vuelta = UserMapper.toResponseDTO(
      UserMapper.toDomain({ ...dto, first_name: null, last_name: null, is_active: false })
    )

    expect(vuelta).toMatchObject({ first_name: null, last_name: null, is_active: false })
  })
})
