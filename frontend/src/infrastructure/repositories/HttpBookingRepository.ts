import type { AxiosInstance } from 'axios'

import { translateRepositoryError } from './BaseRepository'
import type { AppointmentResponseDTO } from '../../application/dtos/BookingDTO'
import { BookingMapper } from '../../application/mappers/BookingMapper'
import { Appointment } from '../../domain/entities/Appointment'
import type {
  AppointmentRange,
  CreateBookingInput,
  IBookingRepository,
  RescheduleInput
} from '../../domain/repositories/IBookingRepository'

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
   * y no cargaba nunca. El `total` de la primera pagina dice cuantas hay; el
   * resto se pide en paralelo (F4-07: en serie, una semana cargada esperaba
   * una ida y vuelta por pagina). Con mas de MAX_PAGES se corta y el llamador
   * lo ve porque `appointments.length < total`.
   */
  async searchByDateRange(
    fromDate: string,
    toDate: string,
    pageSize = MAX_PAGE_SIZE
  ): Promise<AppointmentRange> {
    try {
      const limit = Math.min(Math.max(pageSize, 1), MAX_PAGE_SIZE)
      const fetchPage = async (page: number): Promise<{ total: unknown; batch: Appointment[] }> => {
        const { data } = await this.client.get('/appointments/search', {
          params: { from_date: fromDate, to_date: toDate, page, page_size: limit }
        })
        const results: AppointmentResponseDTO[] = data.results || []
        return { total: data.total, batch: results.map(BookingMapper.toDomain) }
      }

      const first = await fetchPage(1)
      const total = typeof first.total === 'number' ? first.total : first.batch.length
      const pageCount =
        first.batch.length < limit ? 1 : Math.min(Math.ceil(total / limit), MAX_PAGES)
      const rest = await Promise.all(
        Array.from({ length: Math.max(pageCount - 1, 0) }, (_, index) => fetchPage(index + 2))
      )
      const appointments = [first, ...rest].flatMap((page) => page.batch)

      return { appointments, total: Math.max(total, appointments.length) }
    } catch (error) {
      translateRepositoryError('searchByDateRange', error)
    }
  }

  /**
   * Alta del panel para un cliente (FF-04). Iba a `/public/appointments`, que
   * es la reserva del cliente y exige `accepts_terms`: el panel recibia 422.
   * La respuesta no trae nombres (no alcanza para una entidad), asi que solo
   * se devuelve el id; la agenda se refresca por invalidacion.
   */
  async create(payload: CreateBookingInput): Promise<string> {
    try {
      const { data } = await this.client.post<{ public_id: string }>('/appointments/', payload)
      return data.public_id
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

  async reschedule(id: string, input: RescheduleInput): Promise<void> {
    try {
      // El backend recalcula el fin con la duracion del servicio. El flag de
      // fuera de horario viaja solo cuando se pide: su default es false y el
      // backend responde 403 si lo manda alguien que no es administrador.
      await this.client.patch(`/appointments/${id}/reschedule`, {
        new_starts_at: input.newStartsAt,
        idempotency_key: input.idempotencyKey,
        ...(input.allowOutsideSchedule ? { allow_outside_schedule: true } : {})
      })
    } catch (error) {
      translateRepositoryError('reschedule', error)
    }
  }
}
