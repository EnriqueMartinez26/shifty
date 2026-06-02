import { BookingTimeSpan } from './BookingTimeSpan';

describe('BookingTimeSpan Value Object', () => {
  it('debe crear un timespan válido', () => {
    const start = new Date(Date.now() + 10000).toISOString();
    const end = new Date(Date.now() + 20000).toISOString();
    const span = BookingTimeSpan.create(start, end);
    expect(span.getStartsAt().toISOString()).toBe(new Date(start).toISOString());
  });

  it('debe verificar duracion', () => {
    const span = BookingTimeSpan.create('2026-05-18T10:00:00Z', '2026-05-18T11:30:00Z');
    expect(span.getDurationMinutes()).toBe(90);
  });
});
