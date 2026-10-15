import { InvalidValueError } from '../errors/DomainError'

/**
 * Topes de un adicional. Espejan `ServiceAddonInput` del backend y los CHECK
 * de `service_addons` (`ck_service_addons_unit_price`,
 * `ck_service_addons_max_quantity`, `ck_service_addons_position`): un valor
 * fuera de estos rangos lo rechaza Postgres, no solo Pydantic.
 */
export const ADDON_NAME_MAX_LENGTH = 100
export const ADDON_MAX_UNIT_PRICE = 1_000_000
export const ADDON_MIN_QUANTITY = 1
export const ADDON_MAX_QUANTITY = 99
export const MAX_ADDONS_PER_SERVICE = 20

/**
 * Forma de escritura de un adicional. El backend recibe el conjunto entero y
 * actualiza en el lugar los que traen `id` (salvo que cambie el precio: ahi
 * rota el id); los que no lo traen son nuevos.
 */
export interface ServiceAddonInput {
  id?: string | null
  name: string
  unitPrice: number
  maxQuantity: number
}

/** Forma primitiva (la de la API). `id` null: todavia no se guardo. */
export interface ServiceAddonPrimitives {
  id: string | null
  name: string
  unit_price: number
  max_quantity: number
  position: number
}

// Con tolerancia: 0.1 * 100 da 10.000000000000002 en coma flotante.
const hasSubCents = (value: number): boolean =>
  Math.abs(value * 100 - Math.round(value * 100)) > 1e-6

/**
 * Motivo por el que un adicional no es valido, o null. Es la misma regla que
 * el schema del backend; vive aca para que el formulario y la entidad digan
 * lo mismo.
 */
export const serviceAddonIssue = (input: ServiceAddonInput): string | null => {
  const name = input.name.trim()
  if (!name) return 'Cada adicional necesita un nombre'
  if (name.length > ADDON_NAME_MAX_LENGTH) {
    return `El nombre de un adicional no puede superar los ${ADDON_NAME_MAX_LENGTH} caracteres`
  }
  if (
    !Number.isFinite(input.unitPrice) ||
    input.unitPrice < 0 ||
    input.unitPrice > ADDON_MAX_UNIT_PRICE
  ) {
    return 'El precio de un adicional va de 0 a 1.000.000'
  }
  if (hasSubCents(input.unitPrice)) {
    return 'El precio de un adicional no admite fracciones de centavo'
  }
  if (
    !Number.isInteger(input.maxQuantity) ||
    input.maxQuantity < ADDON_MIN_QUANTITY ||
    input.maxQuantity > ADDON_MAX_QUANTITY
  ) {
    return 'La cantidad máxima de un adicional va de 1 a 99'
  }
  return null
}

interface ServiceAddonProps {
  /** null: el adicional todavia no se guardo (alta desde el panel). */
  id: string | null
  name: string
  unitPrice: number
  maxQuantity: number
  position: number
}

const assertValid = (input: ServiceAddonInput): void => {
  const issue = serviceAddonIssue(input)
  if (issue) throw new InvalidValueError('INVALID_ADDON', issue)
}

/**
 * Adicional de un servicio ("Strass", "Diseño"): suma PRECIO por unidad,
 * nunca tiempo (decision de Mateo, 2026-10-14). La duracion del servicio ya
 * cubre el maximo.
 */
export class ServiceAddon {
  private readonly props: ServiceAddonProps

  private constructor(props: ServiceAddonProps) {
    this.props = props
  }

  /** Adicional nuevo, sin id: lo asigna el backend al guardar el servicio. */
  static create(input: ServiceAddonInput, position: number): ServiceAddon {
    assertValid(input)
    return new ServiceAddon({
      id: null,
      name: input.name.trim(),
      unitPrice: input.unitPrice,
      maxQuantity: input.maxQuantity,
      position
    })
  }

  static fromPrimitives(primitives: ServiceAddonPrimitives): ServiceAddon {
    if (primitives.id === '') {
      throw new InvalidValueError('INVALID_ADDON', 'El adicional no tiene identificador')
    }
    assertValid({
      name: primitives.name,
      unitPrice: primitives.unit_price,
      maxQuantity: primitives.max_quantity
    })
    return new ServiceAddon({
      id: primitives.id,
      name: primitives.name.trim(),
      unitPrice: primitives.unit_price,
      maxQuantity: primitives.max_quantity,
      position: primitives.position
    })
  }

  get id() {
    return this.props.id
  }
  get name() {
    return this.props.name
  }
  get unitPrice() {
    return this.props.unitPrice
  }
  get maxQuantity() {
    return this.props.maxQuantity
  }
  get position() {
    return this.props.position
  }

  toPrimitives(): ServiceAddonPrimitives {
    return {
      id: this.props.id,
      name: this.props.name,
      unit_price: this.props.unitPrice,
      max_quantity: this.props.maxQuantity,
      position: this.props.position
    }
  }
}
