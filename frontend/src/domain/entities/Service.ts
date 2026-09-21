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
      isActive: props.is_active
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
      is_active: this.props.isActive
    }
  }
}
