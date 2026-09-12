// ShareLinksPanel usa useServicesCatalog, que importa el singleton
// serviceService -> apiClient real (que a su vez toca runtime-env.ts /
// import.meta, que ts-jest no compila fuera de node_modules). Se mockea
// el modulo del cliente HTTP para poder cargar buildShareLinks sin
// arrastrar esa cadena.
jest.mock('../../../infrastructure/http/client', () => ({
  __esModule: true,
  default: {}
}))

import { buildShareLinks } from './ShareLinksPanel'

describe('buildShareLinks', () => {
  it('arma el link general, uno por servicio y el de mis turnos', () => {
    const links = buildShareLinks('https://app.shifty.com/', 'sol', [
      { public_id: 'svc-1', name: 'Corte' },
      { public_id: 'svc 2', name: 'Color' }
    ])

    expect(links.map((l) => l.url)).toEqual([
      'https://app.shifty.com/b/sol',
      'https://app.shifty.com/b/sol?service=svc-1',
      'https://app.shifty.com/b/sol?service=svc%202',
      'https://app.shifty.com/b/sol/mis-turnos'
    ])
    expect(links[1]?.label).toBe('Corte')
  })

  it('sin slug no hay nada para compartir', () => {
    expect(buildShareLinks('https://app.shifty.com', '', [])).toEqual([])
  })
})
