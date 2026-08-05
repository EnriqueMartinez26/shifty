export type BookingStatusValue =
  'pending' | 'pending_payment' | 'confirmed' | 'completed' | 'cancelled' | 'absent' | 'expired'

export class BookingStatus {
  private readonly value: BookingStatusValue

  private constructor(value: BookingStatusValue) {
    this.value = value
  }

  static create(value: string): BookingStatus {
    const validStatuses: BookingStatusValue[] = [
      'pending',
      'pending_payment',
      'confirmed',
      'completed',
      'cancelled',
      'absent',
      'expired'
    ]
    if (!validStatuses.includes(value as BookingStatusValue)) {
      throw new Error(`Estado de reserva inválido: ${value}`)
    }
    return new BookingStatus(value as BookingStatusValue)
  }

  getValue(): BookingStatusValue {
    return this.value
  }

  isPending(): boolean {
    return this.value === 'pending' || this.value === 'pending_payment'
  }

  isFinalized(): boolean {
    return ['completed', 'cancelled', 'absent', 'expired'].includes(this.value)
  }
}
