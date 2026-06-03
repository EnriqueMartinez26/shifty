import { UserRole } from './UserRole';

describe('UserRole Value Object', () => {
  it('debe instanciar con roles válidos', () => {
    expect(UserRole.create('admin').getValue()).toBe('admin');
    expect(UserRole.create('staff').getValue()).toBe('staff');
    expect(UserRole.create('receptionist').getValue()).toBe('receptionist');
    expect(UserRole.create('client').getValue()).toBe('client');
  });

  it('debe arrojar error con roles inválidos', () => {
    expect(() => UserRole.create('superadmin')).toThrow('Rol inválido: superadmin');
  });

  it('debe verificar rol', () => {
    const role = UserRole.create('admin');
    expect(role.isAdmin()).toBe(true);
    expect(role.isStaff()).toBe(false);
    expect(role.isReceptionist()).toBe(false);
  });

  it('debe igualar roles', () => {
    const r1 = UserRole.create('client');
    const r2 = UserRole.create('client');
    expect(r1.equals(r2)).toBe(true);
  });
});
