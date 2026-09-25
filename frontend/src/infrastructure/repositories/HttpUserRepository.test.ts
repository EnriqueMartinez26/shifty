import type { AxiosInstance } from 'axios'

import { HttpUserRepository } from './HttpUserRepository'
import type { UserResponseDTO } from '../../application/dtos/UserDTO'
import { User } from '../../domain/entities/User'
import { Email } from '../../domain/value-objects/Email'
import { UserRole } from '../../domain/value-objects/UserRole'
import { ConflictError } from '../../shared/errors/ConflictError'
import { InternalServerError } from '../../shared/errors/InternalServerError'

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

  it('el segundo argumento es la clave inicial tipada, no unknown (F10-15)', async () => {
    const { repository } = createRepository()

    // @ts-expect-error: antes `extra` era unknown y un numero compilaba
    await repository.create(nuevo, 42)
  })
})

const createReadRepository = () => {
  const get = jest.fn()
  const remove = jest.fn().mockResolvedValue({ data: null })
  const client = { get, post: jest.fn(), patch: jest.fn(), delete: remove }
  return { get, remove, repository: new HttpUserRepository(client as unknown as AxiosInstance) }
}

describe('HttpUserRepository lecturas', () => {
  it('findAll sin opciones pide solo los activos', async () => {
    const { get, repository } = createReadRepository()
    get.mockResolvedValue({ data: [respuesta] })

    const usuarios = await repository.findAll()

    expect(get).toHaveBeenCalledWith('/users/?include_inactive=false')
    expect(usuarios.map((u) => u.toPrimitives())).toEqual([
      expect.objectContaining({ id: 'usr-1', email: 'ana@example.com' })
    ])
  })

  it('findAll acepta el booleano viejo y el objeto de opciones', async () => {
    const { get, repository } = createReadRepository()
    get.mockResolvedValue({ data: [] })

    await repository.findAll(true)
    await repository.findAll({ includeInactive: true })
    await repository.findAll({})

    expect(get.mock.calls.map((call: unknown[]) => call[0])).toEqual([
      '/users/?include_inactive=true',
      '/users/?include_inactive=true',
      '/users/?include_inactive=false'
    ])
  })

  it('findAll traduce una falla de red a InternalServerError con la operacion', async () => {
    const { get, repository } = createReadRepository()
    get.mockRejectedValue(new Error('Network Error'))

    await expect(repository.findAll()).rejects.toThrow(
      new InternalServerError("Database operation 'findAll' failed: Network Error")
    )
  })

  it('findById devuelve el usuario mapeado', async () => {
    const { get, repository } = createReadRepository()
    get.mockResolvedValue({ data: respuesta })

    const usuario = await repository.findById('usr-1')

    expect(get).toHaveBeenCalledWith('/users/usr-1')
    expect(usuario?.toPrimitives()).toMatchObject({ id: 'usr-1', firstName: 'Ana' })
  })

  it('findById devuelve null ante un 404, no un error', async () => {
    const { get, repository } = createReadRepository()
    get.mockRejectedValue({ response: { status: 404 } })

    await expect(repository.findById('usr-x')).resolves.toBeNull()
  })

  it('findById deja pasar tal cual un error de aplicacion que no es 404', async () => {
    const { get, repository } = createReadRepository()
    const conflicto = new ConflictError('choque')
    get.mockRejectedValue(conflicto)

    await expect(repository.findById('usr-1')).rejects.toBe(conflicto)
  })

  it('findByEmail devuelve el primero o null si no hay coincidencias', async () => {
    const { get, repository } = createReadRepository()
    const email = Email.create('ana@example.com')
    get.mockResolvedValueOnce({ data: [respuesta] }).mockResolvedValueOnce({ data: [] })

    const encontrado = await repository.findByEmail(email)
    const ausente = await repository.findByEmail(email)

    expect(get).toHaveBeenCalledWith('/users/?email=ana@example.com')
    expect(encontrado?.toPrimitives().id).toBe('usr-1')
    expect(ausente).toBeNull()
  })

  it('findByEmail traduce la falla con el nombre de la operacion', async () => {
    const { get, repository } = createReadRepository()
    get.mockRejectedValue(new Error('caido'))

    await expect(repository.findByEmail(Email.create('ana@example.com'))).rejects.toThrow(
      "Database operation 'findByEmail' failed: caido"
    )
  })

  it('findByRole filtra por el rol y mapea cada usuario', async () => {
    const { get, repository } = createReadRepository()
    get.mockResolvedValue({ data: [respuesta, { ...respuesta, public_id: 'usr-2' }] })

    const usuarios = await repository.findByRole(UserRole.create('receptionist'))

    expect(get).toHaveBeenCalledWith('/users/?role=receptionist')
    expect(usuarios.map((u) => u.toPrimitives().id)).toEqual(['usr-1', 'usr-2'])
  })

  it('findByRole traduce la falla a InternalServerError', async () => {
    const { get, repository } = createReadRepository()
    get.mockRejectedValue(new Error('caido'))

    await expect(repository.findByRole(UserRole.create('receptionist'))).rejects.toBeInstanceOf(
      InternalServerError
    )
  })
})

describe('HttpUserRepository.delete', () => {
  it('manda el DELETE a la ruta del usuario', async () => {
    const { remove, repository } = createReadRepository()

    await repository.delete('usr-1')

    expect(remove).toHaveBeenCalledWith('/users/usr-1')
  })

  it('traduce una falla del DELETE con la operacion', async () => {
    const { remove, repository } = createReadRepository()
    remove.mockRejectedValue(new Error('caido'))

    await expect(repository.delete('usr-1')).rejects.toThrow(
      "Database operation 'delete' failed: caido"
    )
  })
})

describe('HttpUserRepository escrituras que fallan', () => {
  it('update con un rechazo que no es Error sale como InternalServerError generico', async () => {
    const { patch, repository } = createRepository()
    patch.mockRejectedValue('respuesta rara')

    await expect(repository.update('usr-1', { firstName: 'Ana' })).rejects.toThrow(
      new InternalServerError("Database operation 'update' failed: Unknown repository error")
    )
  })

  it('create deja pasar un error de aplicacion sin envolverlo', async () => {
    const { post, repository } = createRepository()
    const conflicto = new ConflictError('email repetido')
    post.mockRejectedValue(conflicto)
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

    await expect(repository.create(nuevo)).rejects.toBe(conflicto)
  })
})
