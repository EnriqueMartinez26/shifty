import { toUserListQuery } from './userSearch'

// 2026-09-30 (F4-03): la lista de usuarios cortaba en 200 sin forma de ver el
// resto. Ahora pide paginas de 100 y el resto llega con "Ver mas" (offset).
describe('toUserListQuery', () => {
  it('sin termino lista paginas de 100 con los inactivos', () => {
    expect(toUserListQuery('  ')).toEqual({ limit: 100, includeInactive: true })
  })

  it('un termino de 2 o mas caracteres va como q, con el mismo tope de 100', () => {
    expect(toUserListQuery(' ana ')).toEqual({ limit: 100, includeInactive: true, q: 'ana' })
  })

  it('un termino con @ va como email exacto en minusculas', () => {
    expect(toUserListQuery('Ana@Example.com ')).toEqual({
      limit: 100,
      includeInactive: true,
      email: 'ana@example.com'
    })
  })

  it('no fija offset: la pagina la pone el hook', () => {
    expect(toUserListQuery('ana')).not.toHaveProperty('offset')
  })
})
