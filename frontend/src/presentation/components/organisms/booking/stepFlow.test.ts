import { resolveBackJump, resolveStepJump } from './stepFlow'

const uno = [{ public_id: 'a' }]
const dos = [{ public_id: 'a' }, { public_id: 'b' }]

describe('pasos que se saltean solos', () => {
  it('con varias opciones no saltea nada', () => {
    expect(resolveStepJump(0, { services: dos, staff: dos })).toEqual({ step: 0 })
    expect(resolveStepJump(1, { services: dos, staff: dos })).toEqual({ step: 1 })
  })

  it('un solo servicio y un solo profesional llevan directo al horario', () => {
    expect(resolveStepJump(0, { services: uno, staff: uno })).toEqual({
      step: 2,
      serviceId: 'a',
      staffId: 'a'
    })
  })

  it('un solo servicio con varios profesionales para en el paso del profesional', () => {
    expect(resolveStepJump(0, { services: uno, staff: dos })).toEqual({
      step: 1,
      serviceId: 'a'
    })
  })

  it('mientras las listas cargan no saltea (evita elegir a ciegas)', () => {
    expect(resolveStepJump(0, { services: undefined, staff: undefined })).toEqual({ step: 0 })
    expect(resolveStepJump(1, { services: uno, staff: undefined })).toEqual({ step: 1 })
  })

  it('no toca los pasos posteriores al horario', () => {
    expect(resolveStepJump(3, { services: uno, staff: uno })).toEqual({ step: 3 })
  })
})

describe('volver atras', () => {
  it('sigue de largo por los pasos que se saltearon', () => {
    // Desde el horario, con un solo profesional, vuelve al servicio.
    expect(resolveBackJump(2, { services: dos, staff: uno })).toBe(0)
    // Si ademas hay un solo servicio, no hay a donde volver.
    expect(resolveBackJump(2, { services: uno, staff: uno })).toBe(2)
  })

  it('con varias opciones retrocede de a un paso', () => {
    expect(resolveBackJump(2, { services: dos, staff: dos })).toBe(1)
    expect(resolveBackJump(1, { services: dos, staff: dos })).toBe(0)
    expect(resolveBackJump(0, { services: dos, staff: dos })).toBe(0)
  })
})
