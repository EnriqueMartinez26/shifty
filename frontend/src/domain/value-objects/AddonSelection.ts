import { InvalidValueError } from '../errors/DomainError'

/** Lo minimo de un adicional para elegirlo: lo cumple `ServiceAddon` y el del portal. */
export interface AddonOption {
  id: string
  name: string
  unitPrice: number
  maxQuantity: number
}

export interface AddonLine {
  addonId: string
  name: string
  unitPrice: number
  quantity: number
  amount: number
}

/** Un adicional con su cantidad, para mostrarlo ("Strass x6"). */
export interface AddonQuantity {
  name: string
  quantity: number
}

const toCents = (value: number): number => Math.round(value * 100)

const isValidQuantity = (quantity: number, max: number): boolean =>
  Number.isInteger(quantity) && quantity >= 0 && quantity <= max

/**
 * Cantidades elegidas de los adicionales de UN servicio. Un adicional suma
 * precio por unidad, nunca tiempo. El importe que vale es el que calcula el
 * backend (`price_selection`); este total es el mismo calculo para mostrarlo
 * sin esperar la red, en centavos para no arrastrar error de coma flotante.
 */
export class AddonSelection {
  private readonly selected: readonly AddonLine[]

  private constructor(selected: readonly AddonLine[]) {
    this.selected = selected
  }

  /**
   * Estricta: rechaza un adicional que no es del servicio, una cantidad
   * negativa, fraccionaria o mayor al maximo. Una cantidad 0 no cuenta.
   */
  static create(
    catalog: readonly AddonOption[],
    quantities: Readonly<Record<string, number>>
  ): AddonSelection {
    const byId = new Map(catalog.map((option) => [option.id, option]))
    for (const [addonId, quantity] of Object.entries(quantities)) {
      const option = byId.get(addonId)
      if (!option) {
        if (quantity === 0) continue
        throw new InvalidValueError('ADDON_UNAVAILABLE', 'El adicional no es de este servicio')
      }
      if (!isValidQuantity(quantity, option.maxQuantity)) {
        throw new InvalidValueError(
          'INVALID_ADDON_QUANTITY',
          `La cantidad de ${option.name} va de 0 a ${option.maxQuantity}`
        )
      }
    }
    return AddonSelection.build(catalog, quantities)
  }

  /**
   * Tolerante: descarta lo que el catalogo ya no tiene y acota cada cantidad
   * al rango valido. Es la que se usa despues de volver a pedir el catalogo
   * (un adicional borrado o con un maximo menor no debe trabar la reserva).
   */
  static sanitize(
    catalog: readonly AddonOption[],
    quantities: Readonly<Record<string, number>>
  ): AddonSelection {
    const clamped: Record<string, number> = {}
    for (const option of catalog) {
      const raw = Math.floor(Number(quantities[option.id] ?? 0))
      clamped[option.id] = Number.isFinite(raw) ? Math.min(Math.max(raw, 0), option.maxQuantity) : 0
    }
    return AddonSelection.build(catalog, clamped)
  }

  static empty(): AddonSelection {
    return new AddonSelection([])
  }

  private static build(
    catalog: readonly AddonOption[],
    quantities: Readonly<Record<string, number>>
  ): AddonSelection {
    const lines = catalog
      .map((option) => {
        const quantity = quantities[option.id] ?? 0
        return {
          addonId: option.id,
          name: option.name,
          unitPrice: option.unitPrice,
          quantity,
          amount: (toCents(option.unitPrice) * quantity) / 100
        }
      })
      .filter((line) => line.quantity > 0)
    return new AddonSelection(lines)
  }

  /** Lineas con cantidad mayor a 0, en el orden del catalogo. */
  lines(): AddonLine[] {
    return this.selected.map((line) => ({ ...line }))
  }

  quantityOf(addonId: string): number {
    return this.selected.find((line) => line.addonId === addonId)?.quantity ?? 0
  }

  isEmpty(): boolean {
    return this.selected.length === 0
  }

  total(): number {
    return this.selected.reduce((sum, line) => sum + toCents(line.amount), 0) / 100
  }

  /** Cuerpo de `POST /public/appointments`: sin los adicionales en 0. */
  toPayload(): { addon_id: string; quantity: number }[] {
    return this.selected.map((line) => ({ addon_id: line.addonId, quantity: line.quantity }))
  }

  /** Valores de la query repetida `addon=<id>:<cantidad>` del preview de la seña. */
  toQueryParams(): string[] {
    return this.selected.map((line) => `${line.addonId}:${line.quantity}`)
  }

  /** Las cantidades como mapa, para guardarlas en el estado del wizard. */
  toQuantities(): Record<string, number> {
    return Object.fromEntries(this.selected.map((line) => [line.addonId, line.quantity]))
  }
}

/** "Strass x6". */
export const formatAddonLabel = (addon: AddonQuantity): string => `${addon.name} x${addon.quantity}`

/**
 * "Strass x6, Diseño x1"; vacio si no hay adicionales. Tolera la lista
 * ausente: un turno de un payload viejo no la trae.
 */
export const formatAddonsLabel = (addons: readonly AddonQuantity[] | null | undefined): string =>
  (addons ?? [])
    .filter((addon) => addon.quantity > 0)
    .map(formatAddonLabel)
    .join(', ')
