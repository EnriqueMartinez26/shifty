export class Duration {
  private readonly minutes: number;

  private constructor(minutes: number) {
    this.minutes = minutes;
  }

  static create(minutes: number): Duration {
    if (minutes <= 0) {
      throw new Error("La duración debe ser mayor a 0 minutos");
    }
    if (minutes > 480) { // 8 horas máximo por servicio
      throw new Error("La duración no puede exceder las 8 horas");
    }
    return new Duration(minutes);
  }

  getValue(): number {
    return this.minutes;
  }

  format(): string {
    if (this.minutes < 60) return `${this.minutes} min`;
    const hours = Math.floor(this.minutes / 60);
    const mins = this.minutes % 60;
    return mins > 0 ? `${hours}h ${mins}m` : `${hours}h`;
  }
}
