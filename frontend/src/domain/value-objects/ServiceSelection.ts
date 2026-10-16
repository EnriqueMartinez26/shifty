/** Lo minimo de un servicio para elegirlo junto con otros en un mismo turno. */
export interface ServiceOption {
  id: string
  name: string
  durationMinutes: number
  price: number
}

/** Quien puede atender: los servicios que hace (`service_ids` de /public/staff). */
export interface ServicePerformer {
  serviceIds: readonly string[]
}

/**
 * Tope de servicios en un turno: el principal y hasta dos mas (decision de
 * Mateo, 2026-10-16). El backend responde 422 `TOO_MANY_SERVICES` si se pasa.
 */
export const MAX_SERVICES_PER_BOOKING = 3

/**
 * Tope tecnico de la duracion total: el backend responde 422
 * `SERVICES_TOO_LONG` por encima de esto.
 */
export const MAX_BOOKING_DURATION_MINUTES = 480

/** Por que no se puede sumar un servicio a lo ya elegido. */
export type ServiceBlockReason = 'limit' | 'too_long' | 'no_performer'

const toCents = (value: number): number => Math.round(value * 100)

/**
 * Los servicios elegidos para UN turno, en el orden en que se eligieron: el
 * primero es el principal (el que cuentan los reportes) y los demas viajan
 * como `extra_service_id`. Un mismo profesional los hace todos, uno detras de
 * otro. El precio y la seña los decide el backend: la suma de la lista es
 * solo lo que se muestra antes de pedirlos.
 */
export class ServiceSelection {
  private readonly selected: readonly string[]

  private constructor(selected: readonly string[]) {
    this.selected = selected
  }

  static empty(): ServiceSelection {
    return new ServiceSelection([])
  }

  /** Sin repetidos ni vacios, conservando el orden de eleccion. */
  static of(ids: readonly (string | null | undefined)[]): ServiceSelection {
    const unique: string[] = []
    for (const id of ids) {
      if (id && !unique.includes(id)) unique.push(id)
    }
    return new ServiceSelection(unique)
  }

  /** El principal y los adicionales tal como los guarda el wizard. */
  static fromParts(principalId: string | null, extraIds: readonly string[]): ServiceSelection {
    return principalId ? ServiceSelection.of([principalId, ...extraIds]) : ServiceSelection.empty()
  }

  /** Tocar un servicio lo suma al final o lo quita; quitar el principal asciende al siguiente. */
  toggle(id: string): ServiceSelection {
    return this.includes(id)
      ? new ServiceSelection(this.selected.filter((current) => current !== id))
      : new ServiceSelection([...this.selected, id])
  }

  /** Lo elegido que sigue en el catalogo; un servicio que desaparecio se cae. */
  retainIn(catalog: readonly ServiceOption[]): ServiceSelection {
    const known = new Set(catalog.map((option) => option.id))
    return new ServiceSelection(this.selected.filter((id) => known.has(id)))
  }

  ids(): string[] {
    return [...this.selected]
  }

  principalId(): string | null {
    return this.selected[0] ?? null
  }

  /** Los `extra_service_id` del pedido: todos menos el principal. */
  extraIds(): string[] {
    return this.selected.slice(1)
  }

  count(): number {
    return this.selected.length
  }

  isEmpty(): boolean {
    return this.selected.length === 0
  }

  includes(id: string): boolean {
    return this.selected.includes(id)
  }

  /** Los servicios elegidos del catalogo, en el orden de eleccion. */
  options(catalog: readonly ServiceOption[]): ServiceOption[] {
    const byId = new Map(catalog.map((option) => [option.id, option]))
    return this.selected.flatMap((id) => {
      const option = byId.get(id)
      return option ? [option] : []
    })
  }

  totalDuration(catalog: readonly ServiceOption[]): number {
    return this.options(catalog).reduce((sum, option) => sum + option.durationMinutes, 0)
  }

  /** Suma de los precios de lista, en centavos para no arrastrar error de coma flotante. */
  listPrice(catalog: readonly ServiceOption[]): number {
    return this.options(catalog).reduce((sum, option) => sum + toCents(option.price), 0) / 100
  }

  /** "Corte + Barba". */
  label(catalog: readonly ServiceOption[]): string {
    return this.options(catalog)
      .map((option) => option.name)
      .join(' + ')
  }

  /**
   * Por que `candidate` no se puede sumar, o null si se puede. Un servicio ya
   * elegido siempre se puede tocar (para quitarlo). `performers` es la lista
   * de profesionales con sus servicios; sin ella (cargando) no se bloquea por
   * profesional: el backend igual rechaza un turno sin quien lo haga.
   */
  blockReason(
    candidate: ServiceOption,
    catalog: readonly ServiceOption[],
    performers?: readonly ServicePerformer[]
  ): ServiceBlockReason | null {
    if (this.includes(candidate.id) || this.isEmpty()) return null
    if (this.count() >= MAX_SERVICES_PER_BOOKING) return 'limit'
    if (this.totalDuration(catalog) + candidate.durationMinutes > MAX_BOOKING_DURATION_MINUTES) {
      return 'too_long'
    }
    if (performers) {
      const wanted = [...this.selected, candidate.id]
      const someoneDoesAll = performers.some((performer) =>
        wanted.every((id) => performer.serviceIds.includes(id))
      )
      if (!someoneDoesAll) return 'no_performer'
    }
    return null
  }
}
