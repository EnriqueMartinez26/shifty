import type { AxiosInstance } from 'axios'

import { HttpStaffRepository } from './HttpStaffRepository'
import { ConflictError } from '../../shared/errors/ConflictError'
import { NotFoundError } from '../../shared/errors/NotFoundError'

const staffDto = {
  public_id: 'staff-1',
  kind: 'person',
  first_name: 'Jane',
  last_name: 'Doe',
  email: 'jane@example.com',
  display_name: 'Jane D.',
  is_active: true,
  service_ids: ['s1']
}

describe('HttpStaffRepository.update', () => {
  it('manda a PUT /staff/{id} solo los campos definidos, en snake_case', async () => {
    const put = jest.fn().mockResolvedValue({ data: staffDto })
    const repository = new HttpStaffRepository({ put } as unknown as AxiosInstance)

    const updated = await repository.update('staff-1', {
      displayName: 'Jane D.',
      serviceIds: ['s1']
    })

    expect(put).toHaveBeenCalledWith('/staff/staff-1', {
      display_name: 'Jane D.',
      service_ids: ['s1']
    })
    expect(updated.id).toBe('staff-1')
  })
})

/**
 * FF-35 (2026-09-28): el cliente HTTP ya entrega un 404 como NotFoundError, sin
 * `response`; la rama `response?.status === 404` nunca corria y el 404 salia
 * como error en vez de `null`.
 */
describe('HttpStaffRepository.findById ante un 404', () => {
  const setup = () => {
    const get = jest.fn()
    const client = { get, post: jest.fn(), patch: jest.fn(), put: jest.fn(), delete: jest.fn() }
    return { get, repository: new HttpStaffRepository(client as unknown as AxiosInstance) }
  }

  it('devuelve null, no un error', async () => {
    const { get, repository } = setup()
    get.mockRejectedValue(new NotFoundError('x', { statusCode: 404 }))

    await expect(repository.findById('staff-x')).resolves.toBeNull()
  })

  it('deja pasar tal cual cualquier otro error de aplicacion', async () => {
    const { get, repository } = setup()
    const conflicto = new ConflictError('choque')
    get.mockRejectedValue(conflicto)

    await expect(repository.findById('staff-x')).rejects.toBe(conflicto)
  })
})
