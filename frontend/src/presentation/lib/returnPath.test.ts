import { safeReturnPath } from './returnPath'

/**
 * 2026-09-28 (FF-36, D-20260928-06). Sintoma: al vencer la sesion el login
 * mandaba siempre a la ruta por defecto y se perdia donde estaba. Volver a
 * `from` sin filtrarlo seria un open redirect; estos casos fijan el filtro.
 */
describe('safeReturnPath', () => {
  it.each([
    ['//evil.com'],
    ['/\\evil.com'],
    ['https://x.com/dashboard'],
    ['javascript:alert(1)'],
    ['/login'],
    ['/dashboard\u0000/x'],
    ['dashboard/calendar'],
    [''],
    [undefined],
    [42]
  ])('rechaza %p', (from) => {
    expect(safeReturnPath(from, 'store_admin')).toBeNull()
  })

  it('rechaza una ruta de otro rol, tambien disfrazada con ..', () => {
    expect(safeReturnPath('/control-global', 'professional')).toBeNull()
    expect(safeReturnPath('/dashboard/../control-global', 'store_admin')).toBeNull()
    expect(safeReturnPath('/dashboard/calendar', 'store_admin', true)).toBeNull()
  })

  it('devuelve una ruta interna del area del rol, con su query', () => {
    expect(safeReturnPath('/dashboard/calendar?dia=2026-09-28', 'professional')).toBe(
      '/dashboard/calendar?dia=2026-09-28'
    )
    expect(safeReturnPath('/dashboard', 'admin')).toBe('/dashboard')
    expect(safeReturnPath('/control-global', 'store_admin', true)).toBe('/control-global')
  })
})
