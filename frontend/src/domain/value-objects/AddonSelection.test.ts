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

describe('AddonSelection.reconcile', () => {
  const elegido = (addonId: string, name: string, unitPrice: number, quantity: number) => ({
    addonId,
    name,
    unitPrice,
    quantity
  })

  it('con el mismo catalogo conserva todo y no marca cambios', () => {
    const { selection, changed } = AddonSelection.reconcile(catalog, [
      elegido('strass', 'Strass', 500, 6),
      elegido('diseno', 'Diseño', 1500.1, 1)
    ])

    expect(changed).toBe(false)
    expect(selection.toQuantities()).toEqual({ strass: 6, diseno: 1 })
  })

  it('remapea por nombre si el id cambio y el precio es identico, sin marcar cambios', () => {
    const { selection, changed } = AddonSelection.reconcile(catalog, [
      elegido('strass-viejo', ' strass ', 500, 3)
    ])

    expect(changed).toBe(false)
    expect(selection.toPayload()).toEqual([{ addon_id: 'strass', quantity: 3 }])
  })

  it('con otro precio no remapea: queda en 0 y marca el cambio', () => {
    const { selection, changed } = AddonSelection.reconcile(catalog, [
      elegido('strass-viejo', 'Strass', 400, 3)
    ])

    expect(changed).toBe(true)
    expect(selection.isEmpty()).toBe(true)
  })

  it('el mismo id con otro precio tampoco se conserva', () => {
    const { selection, changed } = AddonSelection.reconcile(catalog, [
      elegido('strass', 'Strass', 400, 3)
    ])

    expect(changed).toBe(true)
    expect(selection.isEmpty()).toBe(true)
  })

  it('un adicional borrado marca el cambio y conserva el resto', () => {
    const { selection, changed } = AddonSelection.reconcile(catalog, [
      elegido('borrado', 'Esmalte', 900, 1),
      elegido('strass', 'Strass', 500, 2)
    ])

    expect(changed).toBe(true)
    expect(selection.toQuantities()).toEqual({ strass: 2 })
  })

  it('una cantidad mayor al maximo nuevo se acota y marca el cambio', () => {
    const { selection, changed } = AddonSelection.reconcile(catalog, [
      elegido('diseno', 'Diseño', 1500.1, 5)
    ])

    expect(changed).toBe(true)
    expect(selection.toQuantities()).toEqual({ diseno: 2 })
  })

  it('dos elegidos que caen en el mismo adicional cuentan una vez y marcan el cambio', () => {
    const { selection, changed } = AddonSelection.reconcile(catalog, [
      elegido('strass', 'Strass', 500, 2),
      elegido('otro-id', 'Strass', 500, 4)
    ])

    expect(changed).toBe(true)
    expect(selection.toQuantities()).toEqual({ strass: 2 })
  })

  it('ignora los elegidos en 0', () => {
    const { selection, changed } = AddonSelection.reconcile(catalog, [
      elegido('borrado', 'Esmalte', 900, 0)
    ])

    expect(changed).toBe(false)
    expect(selection.isEmpty()).toBe(true)
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
