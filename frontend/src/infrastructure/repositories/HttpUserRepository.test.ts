import type { AxiosInstance } from 'axios'

import { HttpUserRepository } from './HttpUserRepository'
import type { UserResponseDTO } from '../../application/dtos/UserDTO'

const respuesta: UserResponseDTO = {
  public_id: 'usr-1',
  email: 'ana@example.com',
  first_name: 'Ana',
  last_name: 'Gomez',
  phone: '1155550101',
  role: 'receptionist',
  is_active: true,
  created_at: '2026-09-01T12:00:00+00:00',
  updated_at: '2026-09-01T12:00:00+00:00'
}

const createRepository = () => {
  const patch = jest.fn().mockResolvedValue({ data: respuesta })
  const client = { get: jest.fn(), post: jest.fn(), patch, delete: jest.fn() }
  return { patch, repository: new HttpUserRepository(client as unknown as AxiosInstance) }
}

describe('HttpUserRepository.update (F11c-11)', () => {
  it('traduce UserWriteInput al PATCH en snake_case', async () => {
    const { patch, repository } = createRepository()

    await repository.update('usr-1', {
      firstName: 'Ana',
      lastName: 'Gomez',
      phone: '1155550101',
      role: 'receptionist',
      isActive: false,
      password: 'claveNueva1234'
    })

    expect(patch).toHaveBeenCalledWith('/users/usr-1', {
      first_name: 'Ana',
      last_name: 'Gomez',
      phone: '1155550101',
      role: 'receptionist',
      is_active: false,
      password: 'claveNueva1234'
    })
  })

  it('no manda la clave vacia ni los campos ausentes', async () => {
    // Editar sin tocar la contraseña deja el campo en '': mandarlo seria un
    // 422 del backend (min 12) o, peor, un intento de pisar la clave.
    const { patch, repository } = createRepository()

    await repository.update('usr-1', { firstName: 'Ana', password: '' })

    expect(patch).toHaveBeenCalledWith('/users/usr-1', { first_name: 'Ana' })
  })
})
