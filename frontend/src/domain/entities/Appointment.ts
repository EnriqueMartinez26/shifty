import { BookingStatus } from '../value-objects/BookingStatus'
import { BookingTimeSpan } from '../value-objects/BookingTimeSpan'
import { UserId } from '../value-objects/UserId'

export interface AppointmentProps {
  id: UserId
  serviceId: string
  serviceName: string
  staffId: string
  staffName: string | null
  clientName: string
  clientPhone: string | null
  timeSpan: BookingTimeSpan
  status: BookingStatus
  notes: string | null
}

export class Appointment {
  private props: AppointmentProps

  private constructor(props: AppointmentProps) {
    this.props = props
  }

  static fromPrimitives(props: {
    public_id: string
    service_id: string
    service_name: string
    staff_id: string
    staff_name?: string | null
    client_name: string
    client_phone?: string | null
    starts_at: string
    ends_at: string
    status: string
    notes: string | null
  }): Appointment {
    return new Appointment({
      id: UserId.create(props.public_id),
      serviceId: props.service_id,
      serviceName: props.service_name,
      staffId: props.staff_id,
      staffName: props.staff_name ?? null,
      clientName: props.client_name,
      clientPhone: props.client_phone ?? null,
      timeSpan: BookingTimeSpan.create(props.starts_at, props.ends_at),
      status: BookingStatus.create(props.status),
      notes: props.notes
    })
  }

  // Getters
  get id() {
    return this.props.id.getValue()
  }
  get serviceId() {
    return this.props.serviceId
  }
  get serviceName() {
    return this.props.serviceName
  }
  get staffId() {
    return this.props.staffId
  }
  get staffName() {
    return this.props.staffName
  }
  get clientName() {
    return this.props.clientName
  }
  get clientPhone(): string | null {
    return this.props.clientPhone
  }
  get timeSpan() {
    return this.props.timeSpan
  }
  get status() {
    return this.props.status.getValue()
  }
  get notes() {
    return this.props.notes
  }

  canBeCancelled(): boolean {
    return !this.props.status.isFinalized() && !this.props.timeSpan.isInPast()
  }

  reschedule(newTimeSpan: BookingTimeSpan): void {
    if (newTimeSpan.isInPast()) throw new Error('No se puede reprogramar a una fecha pasada')
    this.props.timeSpan = newTimeSpan
    this.props.status = BookingStatus.create('pending')
  }

  // Los mutadores confirm() / markAbsent() / complete() se eliminaron a
  // proposito: mutaban el estado sin replicar el grafo de transiciones del
  // backend, y eran una tercera fuente de verdad divergente esperando a que
  // alguien la cableara a un boton. Las transiciones se piden a la API, que es
  // la unica autoridad sobre el estado del turno.

  toPrimitives() {
    return {
      public_id: this.props.id.getValue(),
      service_id: this.props.serviceId,
      service_name: this.props.serviceName,
      staff_id: this.props.staffId,
      staff_name: this.props.staffName,
      client_name: this.props.clientName,
      client_phone: this.props.clientPhone,
      starts_at: this.props.timeSpan.getStartsAt().toISOString(),
      ends_at: this.props.timeSpan.getEndsAt().toISOString(),
      status: this.props.status.getValue(),
      notes: this.props.notes
    }
  }
}
