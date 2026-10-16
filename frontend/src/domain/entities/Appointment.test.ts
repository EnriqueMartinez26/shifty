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

  it('ida y vuelta completa staff y telefono opcionales con null', () => {
    const out = Appointment.fromPrimitives({ ...props, status: 'confirmed' }).toPrimitives()

    expect(out).toEqual({
      ...props,
      status: 'confirmed',
      staff_name: null,
      client_phone: null,
      // Sin el dato se asume que tiene email: no se sugiere WhatsApp de mas.
      client_has_email: true,
      addons: [],
      // Sin la etiqueta del backend, la del servicio.
      services_label: props.service_name,
      starts_at: '2026-09-10T12:00:00.000Z',
      ends_at: '2026-09-10T12:30:00.000Z'
    })
  })

  it('un turno sin email entregable lo conserva en la ida y vuelta', () => {
    const turno = Appointment.fromPrimitives({
      ...props,
      status: 'confirmed',
      client_has_email: false
    })

    expect(turno.clientHasEmail).toBe(false)
    expect(turno.toPrimitives().client_has_email).toBe(false)
  })

  it.each([
    ['fin antes del inicio', { ends_at: '2026-09-10T11:00:00Z' }],
    ['fin igual al inicio', { ends_at: '2026-09-10T12:00:00Z' }],
    ['fecha invalida', { starts_at: 'no-es-fecha' }],
    ['id vacio', { public_id: '' }]
  ])('rechaza %s', (_caso, override) => {
    expect(() => Appointment.fromPrimitives({ ...props, status: 'pending', ...override })).toThrow()
  })
})

describe('Appointment: adicionales', () => {
  it('conserva nombre y cantidad de cada adicional', () => {
    const appointment = Appointment.fromPrimitives({
      ...props,
      status: 'confirmed',
      addons: [{ name: 'Strass', quantity: 6 }]
    })

    expect(appointment.addons).toEqual([{ name: 'Strass', quantity: 6 }])
  })

  it('null equivale a sin adicionales', () => {
    expect(
      Appointment.fromPrimitives({ ...props, status: 'confirmed', addons: null }).addons
    ).toEqual([])
  })
})
