import { Duration } from './Duration';

describe('Duration Value Object', () => {
  it('debe instanciar una duración válida', () => {
    const duration = Duration.create(60);
    expect(duration.getValue()).toBe(60);
  });

  it('debe arrojar error si duración no es positiva o mayor a 8 horas', () => {
    expect(() => Duration.create(0)).toThrow('La duración debe ser mayor a 0 minutos');
    expect(() => Duration.create(-10)).toThrow('La duración debe ser mayor a 0 minutos');
    expect(() => Duration.create(500)).toThrow('La duración no puede exceder las 8 horas');
  });

  it('debe calcular horas y formato legible', () => {
    const duration = Duration.create(90);
    expect(duration.format()).toBe('1h 30m');
  });
});
