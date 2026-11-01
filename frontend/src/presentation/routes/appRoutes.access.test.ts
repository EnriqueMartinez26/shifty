import { SESSION_ROUTES } from './appRoutes'
import { ROLES_ADMIN_SUPER, ROLES_ADMIN_SUPER_PRO, ROLES_SUPER } from '../context/roles'

const tenantRoute = (path: string) => {
  const parent = SESSION_ROUTES.find((route) => route.path === '/dashboard')
  return parent?.children?.find((route) => route.path === path)
}

describe('acceso declarado en las rutas del panel', () => {
  it('restringe rutas de tienda a los mismos grupos nombrados por la navegación', () => {
    expect(tenantRoute('reports')?.access).toBe(ROLES_ADMIN_SUPER_PRO)
    expect(tenantRoute('collections')?.access).toBe(ROLES_ADMIN_SUPER_PRO)
    expect(tenantRoute('ledger')?.access).toBe(ROLES_ADMIN_SUPER_PRO)
    expect(tenantRoute('portal-bookings')?.access).toBe(ROLES_ADMIN_SUPER)

    for (const path of ['payments', 'promotions', 'services', 'staff', 'users', 'settings']) {
      expect(tenantRoute(path)?.access).toBe(ROLES_ADMIN_SUPER)
    }
  })

  it('mantiene agenda, lista de espera, manual y dashboard bajo la sesión autenticada', () => {
    expect(SESSION_ROUTES.find((route) => route.path === '/dashboard')?.access).toBe(
      'authenticated'
    )
    for (const path of ['manual', 'calendar', 'waitlist']) {
      expect(tenantRoute(path)?.access).toBeUndefined()
    }
  })

  it('reserva control global solo para superadmin', () => {
    expect(SESSION_ROUTES.find((route) => route.path === '/control-global')?.access).toBe(
      ROLES_SUPER
    )
  })
})
