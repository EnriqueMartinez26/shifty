import {
  clampStep,
  parseStepParam,
  resolveBackJump,
  resolveStepJump,
  withStepParam
} from './stepFlow'

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

// 2026-10-02 (F4-15): el paso del asistente vivia solo en memoria; "atras" del
// navegador sacaba de la reserva en vez de volver al paso anterior.
describe('paso en la URL (?step=)', () => {
  it.each([
    ['0', 0],
    ['1', 1],
    ['2', 2],
    ['9', 2],
    [' 1 ', 1]
  ])('lee ?step=%p como el paso %p', (crudo, paso) => {
    expect(parseStepParam(crudo)).toBe(paso)
  })

  it.each([null, '', 'abc', '-1', '1.5', '1e3'])('ignora ?step=%p', (crudo) => {
    expect(parseStepParam(crudo)).toBeNull()
  })

  it('el horario sin servicio elegido se degrada al servicio', () => {
    expect(clampStep(1, { serviceId: null, startsAt: null })).toBe(0)
    expect(clampStep(2, { serviceId: null, startsAt: null })).toBe(0)
  })

  it('los datos sin horario elegido se degradan al horario', () => {
    expect(clampStep(2, { serviceId: 'a', startsAt: null })).toBe(1)
  })

  it('con lo elegido respeta el paso pedido', () => {
    expect(clampStep(0, { serviceId: 'a', startsAt: '2026-10-02T12:00:00Z' })).toBe(0)
    expect(clampStep(1, { serviceId: 'a', startsAt: null })).toBe(1)
    expect(clampStep(2, { serviceId: 'a', startsAt: '2026-10-02T12:00:00Z' })).toBe(2)
  })

  it('escribe el paso sin pisar payment_id, service, staff ni date', () => {
    const antes = new URLSearchParams('payment_id=p1&service=a&staff=b&date=2026-10-02')

    const despues = withStepParam(antes, 2, 0)

    expect(despues.get('step')).toBe('2')
    expect(despues.get('payment_id')).toBe('p1')
    expect(despues.get('service')).toBe('a')
    expect(despues.get('staff')).toBe('b')
    expect(despues.get('date')).toBe('2026-10-02')
    // No muta los parametros recibidos.
    expect(antes.has('step')).toBe(false)
  })

  it('el paso de arranque no se escribe: la URL queda limpia', () => {
    expect(withStepParam(new URLSearchParams('step=1&service=a'), 1, 1).toString()).toBe(
      'service=a'
    )
    expect(withStepParam(new URLSearchParams('step=2'), 0, 0).toString()).toBe('')
  })

  it('volver al servicio desde un deep-link deja ?step=0 explicito', () => {
    expect(withStepParam(new URLSearchParams('service=a'), 0, 1).get('step')).toBe('0')
  })
})
