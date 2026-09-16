import { resolveBackJump, resolveStepJump } from './stepFlow'

const uno = [{ public_id: 'a' }]
const dos = [{ public_id: 'a' }, { public_id: 'b' }]

describe('pasos que se saltean solos (wizard de 3 pasos)', () => {
  it('con varios servicios no saltea nada', () => {
    expect(resolveStepJump(0, { services: dos })).toEqual({ step: 0 })
  })

  it('un solo servicio lleva directo al horario con ese servicio elegido', () => {
    expect(resolveStepJump(0, { services: uno })).toEqual({ step: 1, serviceId: 'a' })
  })

  it('mientras la lista carga no saltea (evita elegir a ciegas)', () => {
    expect(resolveStepJump(0, { services: undefined })).toEqual({ step: 0 })
  })

  it('no toca los pasos posteriores al servicio', () => {
    expect(resolveStepJump(1, { services: uno })).toEqual({ step: 1 })
    expect(resolveStepJump(2, { services: uno })).toEqual({ step: 2 })
  })
})

describe('volver atras', () => {
  it('con un solo servicio no hay a donde volver desde el horario', () => {
    expect(resolveBackJump(1, { services: uno })).toBe(1)
    // Desde los datos se vuelve al horario normalmente.
    expect(resolveBackJump(2, { services: uno })).toBe(1)
  })

  it('con varios servicios retrocede de a un paso', () => {
    expect(resolveBackJump(2, { services: dos })).toBe(1)
    expect(resolveBackJump(1, { services: dos })).toBe(0)
    expect(resolveBackJump(0, { services: dos })).toBe(0)
  })
})
