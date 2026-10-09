import { createUuid } from '../../shared/utils/uuid'
import { Email } from '../value-objects/Email'
import { UserId } from '../value-objects/UserId'

type StaffKind = 'person' | 'resource'

/**
 * Lo que se puede cambiar de un staff ya creado. Todo opcional: el backend
 * (`StaffUpdate`) aplica solo lo que llega, asi que editar no necesita leer el
 * registro entero para reenviarlo. `kind` no esta: no cambia despues del alta.
 */
export interface StaffWriteInput {
  firstName?: string
  lastName?: string
  email?: string
  displayName?: string
  serviceIds?: string[]
}

/**
 * Franja de atencion propia del profesional (solo lectura en el front). Las
 * horas son de pared argentina, como las guarda el backend (`HH:MM:SS`);
 * `dayOfWeek` va de 0 = lunes a 6 = domingo, igual que `schedules.day_of_week`.
 */
export interface StaffSchedule {
  dayOfWeek: number
  startTime: string
  endTime: string
}

interface StaffProps {
  id: UserId
  /** 'person' = profesional con login; 'resource' = cancha, sala, box (sin email ni usuario). */
  kind: StaffKind
  firstName: string
  lastName: string
  email: Email | null
  displayName: string | null
  isActive: boolean
  serviceIds: string[]
  schedules: readonly StaffSchedule[]
}

export class Staff {
  private props: StaffProps

  private constructor(props: StaffProps) {
    this.props = props
  }

  static create(props: Omit<StaffProps, 'id' | 'isActive' | 'schedules'>): Staff {
    return new Staff({
      ...props,
      id: UserId.create(createUuid()),
      isActive: true,
      schedules: []
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
    schedules?: readonly { day_of_week: number; start_time: string; end_time: string }[] | null
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
      serviceIds: props.service_ids,
      schedules: (props.schedules ?? []).map((row) => ({
        dayOfWeek: row.day_of_week,
        startTime: row.start_time,
        endTime: row.end_time
      }))
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
  /** Franjas propias; ninguna = atiende en el horario del local (D-20260929-01). */
  get schedules(): readonly StaffSchedule[] {
    return this.props.schedules
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
