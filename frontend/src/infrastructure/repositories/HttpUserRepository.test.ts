import type { AxiosInstance } from 'axios'

import { HttpUserRepository } from './HttpUserRepository'
import type { UserResponseDTO } from '../../application/dtos/UserDTO'
import { User } from '../../domain/entities/User'

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
  const post = jest.fn().mockResolvedValue({ data: respuesta })
  const client = { get: jest.fn(), post, patch, delete: jest.fn() }
  return { patch, post, repository: new HttpUserRepository(client as unknown as AxiosInstance) }
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

describe('HttpUserRepository.create (F10-06)', () => {
  const nuevo = User.fromPrimitives({
    id: 'usr-1',
    email: 'ana@example.com',
    firstName: 'Ana',
    lastName: null,
    phone: null,
    role: 'receptionist',
    isActive: true,
    createdAt: '2026-09-01T12:00:00.000Z'
  })

  it('usa el mismo mapeo que el PATCH: snake_case y los null presentes viajan', async () => {
    const { post, repository } = createRepository()
    const initialSecret = 'x'.repeat(12)

    await repository.create(nuevo, initialSecret)

    expect(post).toHaveBeenCalledWith('/users/', {
      email: 'ana@example.com',
      password: initialSecret,
      first_name: 'Ana',
      last_name: null,
      phone: null,
      role: 'receptionist'
    })
  })

  it('la clave vacia no viaja, igual que en el PATCH', async () => {
    const { post, repository } = createRepository()

    await repository.create(nuevo, '')

    expect(post.mock.calls[0][1]).not.toHaveProperty('password')
  })
})
