import { canonicalRole, getDefaultAppRoute, hasAnyRole, ROLES_ADMIN_SUPER } from './roles'

describe('roles de presentación', () => {
  it.each([
    ['admin', 'store_admin'],
    ['staff', 'professional'],
    ['store_admin', 'store_admin'],
    ['professional', 'professional'],
    ['receptionist', 'receptionist']
  ])('normaliza %s a %s', (role, expected) => {
    expect(canonicalRole(role)).toBe(expected)
  })

  it('el flag global prevalece sobre el rol de tienda para la navegación', () => {
    expect(canonicalRole('client', true)).toBe('super_admin')
    expect(hasAnyRole('client', ROLES_ADMIN_SUPER, true)).toBe(true)
    expect(getDefaultAppRoute('client', true)).toBe('/control-global')
  })

  it('mantiene el destino por defecto de los roles de tienda', () => {
    expect(getDefaultAppRoute('admin')).toBe('/dashboard')
    expect(getDefaultAppRoute('staff')).toBe('/dashboard')
  })
})
