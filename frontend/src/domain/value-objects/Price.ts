export class Price {
  private readonly value: number;
  private readonly currency: string;

  private constructor(value: number, currency: string = 'ARS') {
    this.value = value;
    this.currency = currency;
  }

  static create(value: number, currency: string = 'ARS'): Price {
    if (value < 0) {
      throw new Error("El precio no puede ser negativo");
    }
    return new Price(value, currency);
  }

  getValue(): number {
    return this.value;
  }

  getCurrency(): string {
    return this.currency;
  }

  format(): string {
    return new Intl.NumberFormat('es-AR', {
      style: 'currency',
      currency: this.currency,
    }).format(this.value);
  }
}
