import {
  MAX_BOOKING_DURATION_MINUTES,
  MAX_SERVICES_PER_BOOKING,
  ServiceSelection,
  type ServiceOption
} from './ServiceSelection'

const catalog: ServiceOption[] = [
  { id: 'corte', name: 'Corte', durationMinutes: 30, price: 10000 },
  { id: 'barba', name: 'Barba', durationMinutes: 15, price: 5000.1 },
  { id: 'color', name: 'Color', durationMinutes: 120, price: 30000 },
  { id: 'lavado', name: 'Lavado', durationMinutes: 10, price: 2000 },
  { id: 'alisado', name: 'Alisado', durationMinutes: 400, price: 80000 }
]

const corte = catalog[0] as ServiceOption
const barba = catalog[1] as ServiceOption
const color = catalog[2] as ServiceOption
const lavado = catalog[3] as ServiceOption
const alisado = catalog[4] as ServiceOption

describe('ServiceSelection', () => {
  it('conserva el orden de eleccion: el primero es el principal', () => {
    const selection = ServiceSelection.empty().toggle('barba').toggle('corte')

    expect(selection.ids()).toEqual(['barba', 'corte'])
    expect(selection.principalId()).toBe('barba')
    expect(selection.extraIds()).toEqual(['corte'])
    expect(selection.count()).toBe(2)
    expect(selection.label(catalog)).toBe('Barba + Corte')
  })

  it('tocar uno elegido lo quita y el siguiente pasa a ser el principal', () => {
    const selection = ServiceSelection.of(['corte', 'barba']).toggle('corte')

    expect(selection.principalId()).toBe('barba')
    expect(selection.extraIds()).toEqual([])
    expect(selection.includes('corte')).toBe(false)
  })

  it('descarta repetidos y vacios al construirse', () => {
    expect(ServiceSelection.of(['corte', null, 'corte', '', undefined, 'barba']).ids()).toEqual([
      'corte',
      'barba'
    ])
  })

  it('se arma desde el principal y los adicionales del wizard', () => {
    expect(ServiceSelection.fromParts('corte', ['barba']).ids()).toEqual(['corte', 'barba'])
    expect(ServiceSelection.fromParts(null, ['barba']).isEmpty()).toBe(true)
  })

  it('suma duracion y precio de lista en centavos', () => {
    const selection = ServiceSelection.of(['corte', 'barba'])

    expect(selection.totalDuration(catalog)).toBe(45)
    expect(selection.listPrice(catalog)).toBe(15000.1)
  })

  it('un servicio que ya no esta en el catalogo se cae', () => {
    const selection = ServiceSelection.of(['corte', 'borrado', 'barba']).retainIn(catalog)

    expect(selection.ids()).toEqual(['corte', 'barba'])
    expect(ServiceSelection.of(['borrado']).options(catalog)).toEqual([])
  })

  describe('blockReason', () => {
    const todos = [{ serviceIds: catalog.map((option) => option.id) }]

    it('sin nada elegido, o con el candidato ya elegido, no bloquea', () => {
      expect(ServiceSelection.empty().blockReason(alisado, catalog, [])).toBeNull()
      expect(ServiceSelection.of(['corte']).blockReason(corte, catalog, [])).toBeNull()
    })

    it(`bloquea el servicio numero ${MAX_SERVICES_PER_BOOKING + 1}`, () => {
      const selection = ServiceSelection.of(['corte', 'barba', 'lavado'])

      expect(selection.blockReason(color, catalog, todos)).toBe('limit')
      // Lo ya elegido se puede tocar para quitarlo.
      expect(selection.blockReason(lavado, catalog, todos)).toBeNull()
    })

    it(`bloquea lo que pasa de ${MAX_BOOKING_DURATION_MINUTES} minutos`, () => {
      const selection = ServiceSelection.of(['color'])

      expect(selection.blockReason(alisado, catalog, todos)).toBe('too_long')
      // 30 + 400 = 430: entra.
      expect(ServiceSelection.of(['corte']).blockReason(alisado, catalog, todos)).toBeNull()
    })

    it('bloquea lo que ningun profesional hace junto con lo elegido', () => {
      const performers = [{ serviceIds: ['corte', 'barba'] }, { serviceIds: ['color', 'lavado'] }]
      const selection = ServiceSelection.of(['corte'])

      expect(selection.blockReason(barba, catalog, performers)).toBeNull()
      expect(selection.blockReason(color, catalog, performers)).toBe('no_performer')
    })

    it('sin la lista de profesionales (cargando) no bloquea por profesional', () => {
      expect(ServiceSelection.of(['corte']).blockReason(color, catalog)).toBeNull()
    })
  })
})
