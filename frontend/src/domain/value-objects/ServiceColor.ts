import { InvalidValueError } from '../errors/DomainError'

export class ServiceColor {
  private readonly value: string

  private constructor(value: string) {
    this.value = value
  }

  static create(value: string): ServiceColor {
    // Mismo patrón que el backend (modules/services/schemas.py): acepta hex
    // corto (#FFF) y largo (#FFFFFF). Rechazar el corto acá rompía TODO el
    // listado de servicios apenas uno tuviera un color de 3 dígitos.
    const hexRegex = /^#([0-9A-F]{6}|[0-9A-F]{3})$/i
    if (!hexRegex.test(value)) {
      throw new InvalidValueError('INVALID_COLOR', `Color hexadecimal inválido: ${value}`)
    }
    return new ServiceColor(value)
  }

  getValue(): string {
    return this.value
  }

  equals(other: ServiceColor): boolean {
    return this.value.toLowerCase() === other.getValue().toLowerCase()
  }
}
