import { isBookingStatus, type BookingStatusValue } from '@domain/value-objects/BookingStatus'

import type { UpcomingAppointment } from '@application/services/DashboardService'
import type {
  ProfessionalReportItem,
  ReportAppointmentItem,
  ReportTopServiceItem
} from '@application/services/ReportsService'

import { formatArgentinaDayMonth, formatArgentinaTime } from '@shared/utils/argentinaTime'

import { formatCurrency, numberFormatter } from './dashboardFormatters'
import type { AgendaItem, RankedItem, Tone, TransactionItem } from './types'
import { bookingStatusLabel } from '../../../lib/bookingStatusLabel'

/**
 * La API manda los estados en minusculas (`appointments/model.py`); esto los
 * comparaba en MAYUSCULAS, asi que las tres ramas eran codigo muerto y todo
 * caia en 'neutral': un turno cancelado se pintaba igual que uno confirmado.
 *
 * El mapa completo reemplaza a los tres `includes`: si el backend agrega un
 * estado, `BookingStatusValue` cambia y esto deja de compilar, en vez de
 * volver al gris en silencio. `'REJECTED'` no existia en el enum, y `absent`
 * no estaba en ninguna de las tres listas.
 */
const APPOINTMENT_TONES: Record<BookingStatusValue, Tone> = {
  pending: 'warning',
  pending_payment: 'warning',
  confirmed: 'success',
  completed: 'success',
  cancelled: 'danger',
  absent: 'danger',
  expired: 'danger'
}

export const getAppointmentTone = (status: string): Tone =>
  isBookingStatus(status) ? APPOINTMENT_TONES[status] : 'neutral'

export const getTopProfessional = (items: ProfessionalReportItem[] | undefined) =>
  [...(items ?? [])].sort(
    (left, right) => right.occupancy_rate - left.occupancy_rate || right.revenue - left.revenue
  )[0]

// Los proximos turnos pueden ser de varios dias: cada uno lleva su dia y van
// por hora de inicio (QA 2026-10-02: llegaban sin fecha y desordenados).
export const mapAgenda = (appointments: UpcomingAppointment[] | undefined): AgendaItem[] =>
  [...(appointments ?? [])]
    .sort((left, right) => new Date(left.starts_at).getTime() - new Date(right.starts_at).getTime())
    .map((appointment) => ({
      id: appointment.public_id,
      day: formatArgentinaDayMonth(appointment.starts_at),
      time: formatArgentinaTime(appointment.starts_at),
      title: appointment.client_name,
      subtitle: `${appointment.service_name} - ${appointment.staff_name}`,
      status: bookingStatusLabel(appointment.status),
      tone: getAppointmentTone(appointment.status)
    }))

export const mapTopServices = (items: ReportTopServiceItem[] | undefined): RankedItem[] =>
  (items ?? []).slice(0, 4).map((item) => ({
    id: item.service_id,
    label: item.service_name,
    value: formatCurrency(item.revenue),
    detail: `${numberFormatter.format(item.appointments)} reservas`
  }))

export const mapTransactions = (items: ReportAppointmentItem[] | undefined): TransactionItem[] =>
  [...(items ?? [])]
    .sort((left, right) => new Date(right.starts_at).getTime() - new Date(left.starts_at).getTime())
    .slice(0, 6)
    .map((item) => ({
      id: item.public_id,
      title: item.client_name,
      subtitle: `${item.service_name} - ${formatArgentinaDayMonth(item.starts_at)} ${formatArgentinaTime(item.starts_at)}`,
      amount: formatCurrency(item.service_price),
      status: bookingStatusLabel(item.status),
      tone: getAppointmentTone(item.status)
    }))
