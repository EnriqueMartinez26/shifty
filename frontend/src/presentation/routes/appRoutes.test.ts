import { SESSION_ROUTES, type AppRoute } from './appRoutes'

// La matriz completa ruta x rol vive en App.test.tsx; aca se fija la guarda
// de la limpieza de reservas del portal (S6 antiabuso, 2026-10-22).
const panelChild = (path: string): AppRoute | undefined =>
  SESSION_ROUTES.find((route) => route.path === '/dashboard')?.children?.find(
    (child) => child.path === path
  )

describe('appRoutes: reservas del portal', () => {
  it('la ruta existe dentro del panel y solo entran dueno, administrador y superadmin', () => {
    const route = panelChild('portal-bookings')

    expect(route).toBeDefined()
    expect(route && 'page' in route).toBe(true)
    expect(route?.access).toEqual(['store_admin', 'super_admin'])
  })

  it('las demas rutas del panel conservan su guarda', () => {
    expect(panelChild('waitlist')?.access).toBeUndefined()
    expect(panelChild('calendar')?.access).toBeUndefined()
    expect(panelChild('services')?.access).toEqual(['store_admin', 'super_admin'])
  })
})
