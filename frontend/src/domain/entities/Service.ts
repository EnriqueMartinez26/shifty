import { ServiceAddon, type ServiceAddonInput, type ServiceAddonPrimitives } from './ServiceAddon'
import { createUuid } from '../../shared/utils/uuid'
import { Duration } from '../value-objects/Duration'
import { Price } from '../value-objects/Price'
import { ServiceColor } from '../value-objects/ServiceColor'
import { UserId } from '../value-objects/UserId'

/**
 * Politica de sena del servicio. Los tres valores espejan el contrato del
 * backend (`ServiceBase` en `backend/modules/services/schemas.py` y los CHECK
 * `ck_services_deposit_mode` / `ck_services_deposit_type`). Son primitivos a
 * proposito: la sena no tiene ninguna invariante que el dominio pueda sostener
 * por si solo (la regla cruzada "el monto se exige salvo cuando el tipo es
 * `full`" vive en el schema zod del formulario y en el calculo de cobro del
 * backend), asi que un value object seria una caja sin comportamiento.
 */
export type ServiceDepositMode = 'none' | 'optional' | 'required'
export type ServiceDepositType = 'percent' | 'fixed' | 'full'

/**
 * Diseño previo (S7): un aviso para la clienta, nada mas. No cambia el cobro
 * ni el estado del turno. Tope y normalizacion espejan `ServiceBase` del
 * backend (`prior_design_message`: hasta 500, recortado, vacio es null).
 */
export const MAX_PRIOR_DESIGN_MESSAGE_LENGTH = 500

/** Lo que lee la clienta cuando la tienda no escribio un mensaje propio. */
export const defaultPriorDesignMessage = (storeName: string): string =>
  `Mandale tu diseño a ${storeName} por WhatsApp para que lo vea antes del turno.`

/** Recorta el mensaje; vacio es null. `undefined` sigue siendo "no lo toques". */
export const normalizePriorDesignMessage = (
  message: string | null | undefined
): string | null | undefined => {
  if (message === undefined || message === null) return message
  const trimmed = message.trim()
  return trimmed === '' ? null : trimmed
}

/**
 * Forma de escritura hacia la API. Todo campo es opcional y solo los campos
 * PRESENTES se mandan: un `undefined` no viaja. Esto es lo que evita que
 * editar el nombre de un servicio apague una sena ya configurada.
 */
export interface ServiceWriteInput {
  name?: string
  description?: string | null
  duration?: Duration
  durationMinutes?: number
  price?: number | Price
  color?: string
  imageUrl?: string | null
  youtubeTrailerUrl?: string | null
  depositMode?: ServiceDepositMode
  depositType?: ServiceDepositType
  depositAmount?: number | null
  isActive?: boolean
  requiresPriorDesign?: boolean
  /** `null` lo borra. Se guarda aunque la opcion este apagada. */
  priorDesignMessage?: string | null
  /**
   * Conjunto COMPLETO de adicionales: si viene, el backend reemplaza los que
   * habia (el orden es la posicion). Ausente, no se tocan.
   */
  addons?: readonly ServiceAddonInput[]
}

interface ServiceProps {
  id: UserId
  name: string
  description: string | null
  duration: Duration
  price: Price
  color: ServiceColor
  imageUrl: string | null
  youtubeTrailerUrl: string | null
  depositMode: ServiceDepositMode
  depositType: ServiceDepositType
  depositAmount: number | null
  isActive: boolean
  requiresPriorDesign: boolean
  /** A la clienta se le muestra solo con `requiresPriorDesign`. */
  priorDesignMessage: string | null
  /** Ordenados por posicion. */
  addons: readonly ServiceAddon[]
}

export class Service {
  private props: ServiceProps

  private constructor(props: ServiceProps) {
    this.props = props
  }

  static create(props: Omit<ServiceProps, 'id'>): Service {
    return new Service({
      ...props,
      id: UserId.create(createUuid())
    })
  }

  static fromPrimitives(props: {
    id: string
    name: string
    description: string | null
    duration_minutes: number
    price: number
    color: string | null
    image_url: string | null
    youtube_trailer_url: string | null
    deposit_mode: ServiceDepositMode
    deposit_type: ServiceDepositType
    deposit_amount: number | null
    is_active: boolean
    /** Opcionales: un backend anterior al diseño previo no los manda. */
    requires_prior_design?: boolean
    prior_design_message?: string | null
    /** Opcional: un servicio sin adicionales puede no traer la lista. */
    addons?: readonly ServiceAddonPrimitives[]
  }): Service {
    return new Service({
      id: UserId.create(props.id),
      name: props.name,
      description: props.description,
      duration: Duration.create(props.duration_minutes),
      price: Price.create(props.price),
      color: ServiceColor.create(props.color || '#6366f1'),
      imageUrl: props.image_url,
      youtubeTrailerUrl: props.youtube_trailer_url,
      depositMode: props.deposit_mode,
      depositType: props.deposit_type,
      depositAmount: props.deposit_amount,
      isActive: props.is_active,
      requiresPriorDesign: props.requires_prior_design ?? false,
      priorDesignMessage: props.prior_design_message ?? null,
      addons: [...(props.addons ?? [])]
        .sort((a, b) => a.position - b.position)
        .map((addon) => ServiceAddon.fromPrimitives(addon))
    })
  }

  get id() {
    return this.props.id.getValue()
  }
  get name() {
    return this.props.name
  }
  get description() {
    return this.props.description
  }
  get duration() {
    return this.props.duration
  }
  get price() {
    return this.props.price
  }
  get color() {
    return this.props.color.getValue()
  }
  get imageUrl() {
    return this.props.imageUrl
  }
  get youtubeTrailerUrl() {
    return this.props.youtubeTrailerUrl
  }
  get depositMode() {
    return this.props.depositMode
  }
  get depositType() {
    return this.props.depositType
  }
  get depositAmount() {
    return this.props.depositAmount
  }
  get isActive() {
    return this.props.isActive
  }
  get requiresPriorDesign() {
    return this.props.requiresPriorDesign
  }
  get priorDesignMessage() {
    return this.props.priorDesignMessage
  }
  get addons() {
    return this.props.addons
  }

  toPrimitives() {
    return {
      id: this.props.id.getValue(),
      name: this.props.name,
      description: this.props.description,
      duration_minutes: this.props.duration.getValue(),
      price: this.props.price.getValue(),
      color: this.props.color.getValue(),
      image_url: this.props.imageUrl,
      youtube_trailer_url: this.props.youtubeTrailerUrl,
      deposit_mode: this.props.depositMode,
      deposit_type: this.props.depositType,
      deposit_amount: this.props.depositAmount,
      is_active: this.props.isActive,
      requires_prior_design: this.props.requiresPriorDesign,
      prior_design_message: this.props.priorDesignMessage,
      addons: this.props.addons.map((addon) => addon.toPrimitives())
    }
  }
}
