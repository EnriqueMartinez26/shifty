import { InvalidValueError } from '../errors/DomainError'

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export class Email {
  private readonly value: string

  private constructor(email: string) {
    this.value = email
  }

  static create(email: string): Email {
    const normalized = email.toLowerCase().trim()
    if (!Email.isValid(normalized)) {
      throw new InvalidValueError('INVALID_EMAIL', `Email inválido: ${normalized}`)
    }
    return new Email(normalized)
  }

  /** El mismo criterio que `create`, sin lanzar: para habilitar un formulario. */
  static isValid(email: string): boolean {
    return EMAIL_PATTERN.test(email.toLowerCase().trim())
  }

  getValue(): string {
    return this.value
  }

  equals(other: Email): boolean {
    return this.value === other.getValue()
  }
}
