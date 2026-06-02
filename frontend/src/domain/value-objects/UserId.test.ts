import { UserId } from './UserId';

describe('UserId Value Object', () => {
  it('debe instanciar con un valor válido', () => {
    const id = UserId.create('user-123');
    expect(id.getValue()).toBe('user-123');
  });

  it('debe arrojar error si está vacío', () => {
    expect(() => UserId.create('')).toThrow('UserId inválido: no puede estar vacío');
    expect(() => UserId.create('   ')).toThrow('UserId inválido: no puede estar vacío');
  });

  it('debe igualar correctamente', () => {
    const id1 = UserId.create('123');
    const id2 = UserId.create('123');
    const id3 = UserId.create('456');

    expect(id1.equals(id2)).toBe(true);
    expect(id1.equals(id3)).toBe(false);
  });
});
