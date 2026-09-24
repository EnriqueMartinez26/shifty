import { Appointment } from './Appointment'

const props = {
  public_id: 'appt-1',
  service_id: 'service-1',
  service_name: 'Corte',
  staff_id: 'staff-1',
  client_name: 'Ana',
  starts_at: '2026-09-10T12:00:00Z',
  ends_at: '2026-09-10T12:30:00Z',
  notes: null
}

describe('Appointment.fromPrimitives', () => {
  it('un estado que el front no conoce no tira: se conserva crudo (F8-03)', () => {
    // Antes BookingStatus.create lanzaba y un solo turno con un estado nuevo
    // del backend tumbaba la agenda entera.
    const appointment = Appointment.fromPrimitives({ ...props, status: 'on_hold' })

    expect(appointment.status).toBe('on_hold')
    expect(appointment.toPrimitives().status).toBe('on_hold')
  })
})
