import { createUuid } from '../../shared/utils/uuid'
import { Email } from '../value-objects/Email'
import { UserId } from '../value-objects/UserId'

export type StaffKind = 'person' | 'resource'

export interface StaffProps {
  id: UserId
  /** 'person' = profesional con login; 'resource' = cancha, sala, box (sin email ni usuario). */
  kind: StaffKind
  firstName: string
  lastName: string
  email: Email | null
  displayName: string | null
  isActive: boolean
  serviceIds: string[]
}

export class Staff {
  private props: StaffProps

  private constructor(props: StaffProps) {
    this.props = props
  }

  static create(props: Omit<StaffProps, 'id' | 'isActive'>): Staff {
    return new Staff({
      ...props,
      id: UserId.create(createUuid()),
      isActive: true
    })
  }

  static fromPrimitives(props: {
    public_id: string
    kind?: string | null
    first_name: string
    last_name: string
    email: string | null
    display_name: string | null
    is_active: boolean
    service_ids: string[]
  }): Staff {
    // Un recurso no tiene email: Email.create('') explotaba y tiraba abajo
    // la pagina entera de personal (2026-09-10).
    const email = props.email && props.email.trim() ? Email.create(props.email) : null
    return new Staff({
      id: UserId.create(props.public_id),
      kind: props.kind === 'resource' ? 'resource' : 'person',
      firstName: props.first_name ?? '',
      lastName: props.last_name ?? '',
      email,
      displayName: props.display_name,
      isActive: props.is_active,
      serviceIds: props.service_ids
    })
  }

  // Getters
  get id() {
    return this.props.id.getValue()
  }
  get firstName() {
    return this.props.firstName
  }
  get lastName() {
    return this.props.lastName
  }
  get email(): Email | null {
    return this.props.email
  }
  get kind(): StaffKind {
    return this.props.kind
  }
  get isResource(): boolean {
    return this.props.kind === 'resource'
  }
  get displayName() {
    return this.props.displayName ?? this.fullName
  }
  get isActive() {
    return this.props.isActive
  }
  get serviceIds() {
    return [...this.props.serviceIds]
  }

  get fullName(): string {
    const nombre = `${this.props.firstName} ${this.props.lastName}`.trim()
    return nombre || (this.props.displayName ?? '')
  }

  // Business Logic
  assignToService(serviceId: string): void {
    if (!this.props.serviceIds.includes(serviceId)) {
      this.props.serviceIds.push(serviceId)
    }
  }

  removeFromService(serviceId: string): void {
    this.props.serviceIds = this.props.serviceIds.filter((id) => id !== serviceId)
  }

  toPrimitives() {
    return {
      public_id: this.props.id.getValue(),
      kind: this.props.kind,
      first_name: this.props.firstName,
      last_name: this.props.lastName,
      email: this.props.email ? this.props.email.getValue() : null,
      display_name: this.props.displayName,
      is_active: this.props.isActive,
      service_ids: [...this.props.serviceIds]
    }
  }
}
