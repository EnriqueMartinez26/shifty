export type BookingStatusValue =
  'pending' | 'pending_payment' | 'confirmed' | 'completed' | 'cancelled' | 'absent' | 'expired'

/**
 * Estados absorbentes del turno.
 *
 * Replica el conjunto derivado de ALLOWED_STATUS_TRANSITIONS en el backend
 * (infrastructure/persistence/models/appointment.py). La equivalencia esta
 * congelada por test_el_conjunto_de_estados_terminales_es_el_documentado:
 * si el backend agrega un estado terminal, su CI falla indicando que hay que
 * actualizar esta lista.
 */
export const TERMINAL_STATUSES: readonly BookingStatusValue[] = [
  'completed',
  'cancelled',
  'absent',
  'expired'
] as const

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
    return TERMINAL_STATUSES.includes(this.value)
  }
}
