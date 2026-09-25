import { InvalidValueError } from '../errors/DomainError'

export class UserId {
  private readonly value: string

  private constructor(value: string) {
    this.value = value
  }

  static create(value: string): UserId {
    if (!value || value.trim().length === 0) {
      throw new InvalidValueError('INVALID_USER_ID', 'UserId inválido: no puede estar vacío')
    }
    // Id opaco a proposito: llegan ULID del backend (26 caracteres) y UUID de
    // createUuid(). Exigir formato UUID rechazaria todos los ids del backend.
    return new UserId(value.trim())
  }

  getValue(): string {
    return this.value
  }

  equals(other: UserId): boolean {
    return this.value === other.getValue()
  }
}
