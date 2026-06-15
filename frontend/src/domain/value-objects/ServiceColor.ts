export class ServiceColor {
  private readonly value: string

  private constructor(value: string) {
    this.value = value
  }

  static create(value: string): ServiceColor {
    const hexRegex = /^#[0-9A-F]{6}$/i
    if (!hexRegex.test(value)) {
      throw new Error(`Color hexadecimal inválido: ${value}`)
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
