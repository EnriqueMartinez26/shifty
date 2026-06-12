export class UserId {
  private readonly value: string

  private constructor(value: string) {
    this.value = value
  }

  static create(value: string): UserId {
    if (!value || value.trim().length === 0) {
      throw new Error(`UserId inválido: no puede estar vacío`)
    }
    // Opcional: Validar formato UUID si aplica
    return new UserId(value.trim())
  }

  getValue(): string {
    return this.value
  }

  equals(other: UserId): boolean {
    return this.value === other.getValue()
  }
}
