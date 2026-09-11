import { StaffMapper } from './StaffMapper'
import { Staff } from '../../domain/entities/Staff'

const recurso = Staff.fromPrimitives({
  public_id: 'cancha-1',
  kind: 'resource',
  first_name: '',
  last_name: '',
  email: null,
  display_name: 'Cancha 1',
  is_active: true,
  service_ids: ['s1']
})

const persona = Staff.fromPrimitives({
  public_id: 'st-1',
  kind: 'person',
  first_name: 'Ana',
  last_name: 'Perez',
  email: 'ana@example.com',
  display_name: 'Ana P.',
  is_active: true,
  service_ids: ['s1']
})

describe('StaffMapper.toWritePayload', () => {
  it('un recurso no manda nombre ni email (el backend exige min_length=1)', () => {
    // Regresion 2026-09-11: editar una cancha siempre fallaba con 422.
    const payload = StaffMapper.toWritePayload(recurso)

    expect(payload).not.toHaveProperty('first_name')
    expect(payload).not.toHaveProperty('last_name')
    expect(payload).not.toHaveProperty('email')
    expect(payload).toMatchObject({ kind: 'resource', display_name: 'Cancha 1' })
  })

  it('una persona manda el payload completo', () => {
    expect(StaffMapper.toWritePayload(persona)).toMatchObject({
      first_name: 'Ana',
      last_name: 'Perez',
      email: 'ana@example.com'
    })
  })
})
