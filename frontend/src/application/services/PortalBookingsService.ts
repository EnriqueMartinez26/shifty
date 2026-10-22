import apiClient from '@infrastructure/http/client'

/** Tope de `appointment_ids` de POST /appointments/bulk-cancel. */
const BULK_CANCEL_MAX_IDS = 100

/** Ventanas que ofrece el panel; el backend acepta de 1 a 168 horas. */
export type PortalBookingsWindowHours = 24 | 72 | 168

/** Turno futuro y activo que alguien reservo desde el portal publico. */
export interface RecentPortalBooking {
  public_id: string
  client_name: string
  client_phone: string | null
  service_name: string
  staff_name: string
  starts_at: string
  created_at: string
  status: string
}

/** Turno que la cancelacion masiva no toco, con el motivo del backend. */
export interface BulkCancelSkipped {
  id: string
  code: string
}

export interface BulkCancelResult {
  cancelled: string[]
  skipped: BulkCancelSkipped[]
}

/**
 * Limpieza de reservas sospechosas del portal (solo el dueno o administrador).
 * Cancela por el mismo camino que el panel: vence el cobro vivo y avisa por
 * mail al cliente que dejo uno.
 */
class PortalBookingsService {
  async listRecent(hours: PortalBookingsWindowHours): Promise<RecentPortalBooking[]> {
    const { data } = await apiClient.get<RecentPortalBooking[] | null>(
      '/appointments/recent-portal',
      { params: { hours } }
    )
    return Array.isArray(data) ? data : []
  }

  /**
   * El backend acepta hasta 100 ids por pedido: "Seleccionar todas" sobre una
   * ventana con mas reservas se manda en tandas, una despues de otra, y los
   * resultados se juntan. Si una tanda falla, el error sube y las anteriores
   * ya quedaron canceladas (la lista refrescada lo muestra).
   */
  async bulkCancel(appointmentIds: string[], reason?: string): Promise<BulkCancelResult> {
    const trimmedReason = reason?.trim()
    const result: BulkCancelResult = { cancelled: [], skipped: [] }
    for (let start = 0; start < appointmentIds.length; start += BULK_CANCEL_MAX_IDS) {
      const { data } = await apiClient.post<Partial<BulkCancelResult> | null>(
        '/appointments/bulk-cancel',
        {
          appointment_ids: appointmentIds.slice(start, start + BULK_CANCEL_MAX_IDS),
          ...(trimmedReason ? { reason: trimmedReason } : {})
        }
      )
      result.cancelled.push(...(data?.cancelled ?? []))
      result.skipped.push(...(data?.skipped ?? []))
    }
    return result
  }
}

export const portalBookingsService = new PortalBookingsService()
