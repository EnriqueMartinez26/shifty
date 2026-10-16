import { toSessionUser } from './CurrentUserMapper'
import type { CurrentUserDTO } from '../dtos/CurrentUserDTO'

// 2026-10-14, produccion: /me no traia nombre ni apellido y "Agregarme como
// profesional" abria con el nombre visible vacio aunque la cuenta lo tuviera.

const dto: CurrentUserDTO = {
  email: 'duenio@example.com',
  role: 'admin',
  store_id: 'st-1',
  public_id: 'usr-1',
  is_global_admin: false,
  first_name: 'Enrique',
  last_name: 'Martinez'
}

describe('toSessionUser', () => {
  it('mapea cada campo de /me, nombre y apellido incluidos', () => {
    expect(toSessionUser(dto)).toEqual({
      email: 'duenio@example.com',
      role: 'admin',
      store_id: 'st-1',
      public_id: 'usr-1',
      is_global_admin: false,
      first_name: 'Enrique',
      last_name: 'Martinez'
    })
  })

  it('un nombre null queda sin nombre, nunca como texto', () => {
    const user = toSessionUser({ ...dto, first_name: null, last_name: null })

    expect(user.first_name).toBeUndefined()
    expect(user.last_name).toBeUndefined()
  })

  it('recorta espacios y trata un nombre en blanco como ausente', () => {
    const user = toSessionUser({ ...dto, first_name: '  Enrique ', last_name: '   ' })

    expect(user.first_name).toBe('Enrique')
    expect(user.last_name).toBeUndefined()
  })

  it('tolera un backend anterior que no mandaba los campos', () => {
    const legacy: Partial<CurrentUserDTO> = { ...dto }
    delete legacy.first_name
    delete legacy.last_name
    const user = toSessionUser(legacy as CurrentUserDTO)

    expect(user.first_name).toBeUndefined()
    expect(user.last_name).toBeUndefined()
    expect(user.email).toBe('duenio@example.com')
  })
})
