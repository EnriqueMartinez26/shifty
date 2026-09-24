import type { AxiosInstance } from 'axios'

import { HttpStaffRepository } from './HttpStaffRepository'

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
