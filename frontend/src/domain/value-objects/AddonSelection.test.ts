import {
  AddonSelection,
  formatAddonLabel,
  formatAddonsLabel,
  type AddonOption
} from './AddonSelection'

const catalog: AddonOption[] = [
  { id: 'strass', name: 'Strass', unitPrice: 500, maxQuantity: 10 },
  { id: 'diseno', name: 'Diseño', unitPrice: 1500.1, maxQuantity: 2 }
]

describe('AddonSelection.create', () => {
  it('suma precio por unidad y descarta los ceros', () => {
    const selection = AddonSelection.create(catalog, { strass: 6, diseno: 0 })

    expect(selection.total()).toBe(3000)
    expect(selection.isEmpty()).toBe(false)
    expect(selection.toPayload()).toEqual([{ addon_id: 'strass', quantity: 6 }])
    expect(selection.toQueryParams()).toEqual(['strass:6'])
    expect(selection.toQuantities()).toEqual({ strass: 6 })
    expect(selection.quantityOf('diseno')).toBe(0)
  })

  it('suma en centavos, sin error de coma flotante', () => {
    const selection = AddonSelection.create(catalog, { strass: 1, diseno: 2 })

    expect(selection.total()).toBe(3500.2)
    expect(selection.lines()).toEqual([
      { addonId: 'strass', name: 'Strass', unitPrice: 500, quantity: 1, amount: 500 },
      { addonId: 'diseno', name: 'Diseño', unitPrice: 1500.1, quantity: 2, amount: 3000.2 }
    ])
  })

  it('sin cantidades es una seleccion vacia', () => {
    const selection = AddonSelection.create(catalog, {})

    expect(selection.isEmpty()).toBe(true)
    expect(selection.total()).toBe(0)
    expect(selection.toPayload()).toEqual([])
    expect(AddonSelection.empty().isEmpty()).toBe(true)
  })

  it('ignora un id desconocido en 0', () => {
    expect(AddonSelection.create(catalog, { otro: 0 }).isEmpty()).toBe(true)
  })

  it('rechaza un adicional que no es del servicio', () => {
    expect(() => AddonSelection.create(catalog, { otro: 1 })).toThrow(
      expect.objectContaining({ code: 'ADDON_UNAVAILABLE' })
    )
  })

  it.each([
    ['mayor al maximo', 11],
    ['negativa', -1],
    ['fraccionaria', 1.5]
  ])('rechaza una cantidad %s', (_caso, quantity) => {
    expect(() => AddonSelection.create(catalog, { strass: quantity })).toThrow(
      expect.objectContaining({ code: 'INVALID_ADDON_QUANTITY' })
    )
  })
})

describe('AddonSelection.sanitize', () => {
  it('descarta lo que el catalogo ya no tiene y acota al maximo', () => {
    const selection = AddonSelection.sanitize(catalog, { strass: 50, diseno: -3, borrado: 4 })

    expect(selection.toQuantities()).toEqual({ strass: 10 })
  })

  it('redondea hacia abajo una cantidad fraccionaria y anula lo que no es numero', () => {
    const selection = AddonSelection.sanitize(catalog, { strass: 2.7, diseno: Number.NaN })

    expect(selection.toQuantities()).toEqual({ strass: 2 })
  })
})

describe('etiquetas', () => {
  it('formatea "Strass x6"', () => {
    expect(formatAddonLabel({ name: 'Strass', quantity: 6 })).toBe('Strass x6')
  })

  it('une varias y saltea las cantidades en 0', () => {
    expect(
      formatAddonsLabel([
        { name: 'Strass', quantity: 6 },
        { name: 'Diseño', quantity: 0 },
        { name: 'Esmalte', quantity: 1 }
      ])
    ).toBe('Strass x6, Esmalte x1')
    expect(formatAddonsLabel([])).toBe('')
    expect(formatAddonsLabel(undefined)).toBe('')
    expect(formatAddonsLabel(null)).toBe('')
  })
})
