export class BookingTimeSpan {
  private readonly startsAt: Date
  private readonly endsAt: Date

  private constructor(startsAt: Date, endsAt: Date) {
    this.startsAt = startsAt
    this.endsAt = endsAt
  }

  static create(startsAt: string | Date, endsAt: string | Date): BookingTimeSpan {
    const start = new Date(startsAt)
    const end = new Date(endsAt)

    if (isNaN(start.getTime()) || isNaN(end.getTime())) {
      throw new Error('Fechas de inicio o fin inválidas')
    }

    if (start >= end) {
      throw new Error('La fecha de inicio debe ser anterior a la fecha de fin')
    }

    return new BookingTimeSpan(start, end)
  }

  getStartsAt(): Date {
    return this.startsAt
  }

  getEndsAt(): Date {
    return this.endsAt
  }

  getDurationMinutes(): number {
    return Math.round((this.endsAt.getTime() - this.startsAt.getTime()) / 60000)
  }

  isInPast(): boolean {
    return this.startsAt < new Date()
  }

  formatDate(): string {
    return this.startsAt.toISOString().split('T')[0]
  }

  formatStartTime(): string {
    return this.startsAt.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })
  }
}
