import { InvalidValueError } from '../errors/DomainError'

type RoleValue = 'admin' | 'staff' | 'receptionist' | 'client'

export class UserRole {
  private readonly value: RoleValue

  private constructor(value: RoleValue) {
    this.value = value
  }

  static create(value: string): UserRole {
    const validRoles: RoleValue[] = ['admin', 'staff', 'receptionist', 'client']
    if (!validRoles.includes(value as RoleValue)) {
      throw new InvalidValueError('INVALID_ROLE', `Rol inválido: ${value}`)
    }
    return new UserRole(value as RoleValue)
  }

  getValue(): RoleValue {
    return this.value
  }

  isAdmin(): boolean {
    return this.value === 'admin'
  }

  isStaff(): boolean {
    return this.value === 'staff'
  }

  isReceptionist(): boolean {
    return this.value === 'receptionist'
  }

  equals(other: UserRole): boolean {
    return this.value === other.getValue()
  }
}
