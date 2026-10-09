import { formatCurrency } from '@shared/utils/currency'

import { InvalidValueError } from '../errors/DomainError'

export class Price {
  private readonly value: number
  private readonly currency: string

  private constructor(value: number, currency: string = 'ARS') {
    this.value = value
    this.currency = currency
  }

  static create(value: number, currency: string = 'ARS'): Price {
    if (value < 0) {
      throw new InvalidValueError('INVALID_PRICE', 'El precio no puede ser negativo')
    }
    return new Price(value, currency)
  }

  getValue(): number {
    return this.value
  }

  getCurrency(): string {
    return this.currency
  }

  format(): string {
    return formatCurrency(this.value, this.currency)
  }
}
