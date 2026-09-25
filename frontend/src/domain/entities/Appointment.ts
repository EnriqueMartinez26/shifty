import { BookingTimeSpan } from '../value-objects/BookingTimeSpan'
import { UserId } from '../value-objects/UserId'

interface AppointmentProps {
  id: UserId
  serviceId: string
  serviceName: string
  staffId: string
  staffName: string | null
  clientName: string
  clientPhone: string | null
  timeSpan: BookingTimeSpan
  /**
   * Crudo a proposito: un estado que el front todavia no conoce no puede
   * tumbar la agenda entera. Las reglas viven en BookingStatus.ts
   * (isBookingStatus, bookingActionsFor) y un desconocido no ofrece acciones.
   */
  status: string
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
      status: props.status,
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
  get status(): string {
    return this.props.status
  }
  get notes() {
    return this.props.notes
  }

  // Los mutadores confirm() / markAbsent() / complete() / reschedule() se
  // eliminaron a proposito: mutaban el estado a mano (reschedule() forzaba
  // 'pending', una transicion que ni siquiera existe en
  // ALLOWED_STATUS_TRANSITIONS para 'confirmed') sin replicar el grafo real
  // del backend, y eran una tercera fuente de verdad divergente esperando a
  // que alguien la cableara a un boton. Las transiciones se piden a la API,
  // que es la unica autoridad sobre el estado del turno.

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
      status: this.props.status,
      notes: this.props.notes
    }
  }
}
