import { initialStepFor, resolveBookingPreselect } from './deepLink'

const services = [{ public_id: 'svc-1' }, { public_id: 'svc-2' }]
const staff = [{ public_id: 'st-1' }]

describe('deep-link de la reserva publica', () => {
  it('preselecciona servicio y profesional validos y arranca en el horario', () => {
    const pre = resolveBookingPreselect({ service: 'svc-1', staff: 'st-1' }, services, staff)
    expect(pre).toEqual({ serviceId: 'svc-1', staffId: 'st-1' })
    expect(initialStepFor(pre)).toBe(2)
  })

  it('con solo el servicio arranca en el paso del profesional', () => {
    const pre = resolveBookingPreselect({ service: 'svc-2', staff: null }, services, staff)
    expect(pre).toEqual({ serviceId: 'svc-2', staffId: null })
    expect(initialStepFor(pre)).toBe(1)
  })

  it('ignora ids que no existen en las listas publicas', () => {
    expect(resolveBookingPreselect({ service: 'otro', staff: 'st-1' }, services, staff)).toEqual({
      serviceId: null,
      staffId: null
    })
    const soloServicio = resolveBookingPreselect(
      { service: 'svc-1', staff: 'ajeno' },
      services,
      staff
    )
    expect(soloServicio).toEqual({ serviceId: 'svc-1', staffId: null })
  })

  it('sin parametros arranca desde el principio', () => {
    const pre = resolveBookingPreselect({ service: null, staff: null }, services, staff)
    expect(initialStepFor(pre)).toBe(0)
  })
})
