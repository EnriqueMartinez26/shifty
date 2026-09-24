import type { AxiosInstance } from 'axios'

import { translateRepositoryError } from './BaseRepository'
import type {
  AppointmentResponseDTO,
  CreateBookingRequestDTO
} from '../../application/dtos/BookingDTO'
import { BookingMapper } from '../../application/mappers/BookingMapper'
import { Appointment } from '../../domain/entities/Appointment'
import type {
  AppointmentRange,
  IBookingRepository
} from '../../domain/repositories/IBookingRepository'
import { createUuid } from '../../shared/utils/uuid'

/** Tope de `page_size` que acepta GET /appointments/search en el backend. */
const MAX_PAGE_SIZE = 100

/**
 * Tope de paginas por rango (5.000 turnos con page_size 100). Lo que pase de
 * ahi no se trae: se devuelve el `total` del servidor para que la agenda avise
 * que la lista esta recortada (F10-12).
 */
const MAX_PAGES = 50

/**
 * Repositorio de turnos. No es un CRUD generico (no extiende BaseRepository):
 * el backend no expone GET/PUT/DELETE por id, asi que solo implementa lo que
 * declara IBookingRepository y cada transicion va a su endpoint.
 */
export class HttpBookingRepository implements IBookingRepository {
  private client: AxiosInstance

  constructor(client: AxiosInstance) {
    this.client = client
  }

  /**
   * Trae todos los turnos de un rango, paginando.
   *
   * El backend tope `page_size` en 100. Antes esta firma tenia un `page`
   * tercero que la interfaz no declara, asi que el `pageSize` del llamador
   * caia en `page` y salia `page=500&page_size=500`: la agenda respondia 422
   * y no cargaba nunca. Ahora la firma coincide con IBookingRepository y se
   * recorren las paginas hasta agotar el rango. El `total` de la primera
   * pagina dice cuantas hay; con mas de MAX_PAGES se corta y el llamador lo
   * ve porque `appointments.length < total`.
   */
  async searchByDateRange(
    fromDate: string,
    toDate: string,
    pageSize = MAX_PAGE_SIZE
  ): Promise<AppointmentRange> {
    try {
      const limit = Math.min(Math.max(pageSize, 1), MAX_PAGE_SIZE)
      const appointments: Appointment[] = []
      let total = 0

      for (let page = 1; page <= MAX_PAGES; page += 1) {
        const { data } = await this.client.get('/appointments/search', {
          params: {
            from_date: fromDate,
            to_date: toDate,
            page,
            page_size: limit
          }
        })
        const batch: AppointmentResponseDTO[] = data.results || []
        appointments.push(...batch.map(BookingMapper.toDomain))
        if (page === 1) total = typeof data.total === 'number' ? data.total : batch.length
        if (batch.length < limit || appointments.length >= total) break
      }

      return { appointments, total: Math.max(total, appointments.length) }
    } catch (error) {
      translateRepositoryError('searchByDateRange', error)
    }
  }

  async create(payload: CreateBookingRequestDTO): Promise<Appointment> {
    try {
      const { data } = await this.client.post<AppointmentResponseDTO>(
        '/public/appointments',
        payload
      )
      return BookingMapper.toDomain(data)
    } catch (error) {
      translateRepositoryError('create', error)
    }
  }

  async confirm(id: string): Promise<void> {
    try {
      await this.client.patch(`/appointments/${id}/confirm`)
    } catch (error) {
      translateRepositoryError('confirm', error)
    }
  }

  async complete(id: string): Promise<void> {
    try {
      await this.client.patch(`/appointments/${id}/complete`)
    } catch (error) {
      translateRepositoryError('complete', error)
    }
  }

  async cancel(id: string): Promise<void> {
    try {
      await this.client.patch(`/appointments/${id}/cancel`)
    } catch (error) {
      translateRepositoryError('cancel', error)
    }
  }

  async release(id: string): Promise<void> {
    try {
      await this.client.patch(`/appointments/${id}/release`)
    } catch (error) {
      translateRepositoryError('release', error)
    }
  }

  async markAbsent(id: string): Promise<void> {
    try {
      await this.client.patch(`/appointments/${id}/absent`)
    } catch (error) {
      translateRepositoryError('markAbsent', error)
    }
  }

  async reschedule(id: string, newStartTime: string): Promise<void> {
    try {
      // El backend recalcula el fin a partir de la duracion del servicio, asi
      // que solo manda el nuevo inicio + una clave de idempotencia.
      await this.client.patch(`/appointments/${id}/reschedule`, {
        new_starts_at: newStartTime,
        idempotency_key: createUuid()
      })
    } catch (error) {
      translateRepositoryError('reschedule', error)
    }
  }
}
