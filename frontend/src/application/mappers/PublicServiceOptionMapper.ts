import type { ServiceOption, ServicePerformer } from '../../domain/value-objects/ServiceSelection'
import type { PublicService, PublicStaff } from '../services/PublicBookingService'

/**
 * Los servicios del portal como opciones para elegir varios en un turno. Vive
 * aparte de PublicBookingService para que la pantalla no arrastre el cliente
 * HTTP al importarlo.
 */
export const publicServiceOptions = (
  services: readonly PublicService[] | undefined
): ServiceOption[] =>
  (services ?? []).map((service) => ({
    id: service.public_id,
    name: service.name,
    durationMinutes: Number(service.duration_minutes),
    price: Number(service.price)
  }))

/** Quien atiende y que servicios hace (`service_ids` de /public/staff). */
export const publicPerformers = (staff: readonly PublicStaff[]): ServicePerformer[] =>
  staff.map((member) => ({ serviceIds: member.service_ids ?? [] }))

/**
 * Los profesionales que hacen TODOS los servicios elegidos: la grilla de un
 * turno con varios servicios es la de ellos. Sin adicionales es la lista tal
 * cual llego (la del servicio principal).
 */
export const staffForAllServices = <T extends Pick<PublicStaff, 'service_ids'>>(
  staff: readonly T[],
  extraServiceIds: readonly string[]
): T[] =>
  staff.filter((member) => extraServiceIds.every((id) => (member.service_ids ?? []).includes(id)))
