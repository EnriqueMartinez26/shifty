import type { AxiosInstance } from 'axios'

import { subDays } from 'date-fns'

import { BaseRepository } from './BaseRepository'
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
import { QueryOptions } from '../../domain/repositories/IRepository'
import { formatArgentinaDate } from '../../shared/utils/argentinaTime'
import { createUuid } from '../../shared/utils/uuid'

type BookingUpdatePayload = {
  notes_staff?: string
}

/** Tope de `page_size` que acepta GET /appointments/search en el backend. */
const MAX_PAGE_SIZE = 100

/**
 * Tope de paginas por rango (5.000 turnos con page_size 100). Lo que pase de
 * ahi no se trae: se devuelve el `total` del servidor para que la agenda avise
 * que la lista esta recortada (F10-12).
 */
const MAX_PAGES = 50

export class HttpBookingRepository
  extends BaseRepository<Appointment, CreateBookingRequestDTO, BookingUpdatePayload>
  implements IBookingRepository
{
  private client: AxiosInstance

  constructor(client: AxiosInstance) {
    super()
    this.client = client
  }

  async findByDate(date: string): Promise<Appointment[]> {
    try {
      const { data } = await this.client.get<AppointmentResponseDTO[]>(
        `/appointments/?date=${date}`
      )
      return data.map(BookingMapper.toDomain)
    } catch (error) {
      this.handleRepositoryError('findByDate', error)
    }
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
      this.handleRepositoryError('searchByDateRange', error)
    }
  }

  async getAvailability(serviceId: string, date: string): Promise<Record<string, unknown>> {
    try {
      const { data } = await this.client.get(
        `/appointments/availability?service_id=${serviceId}&date=${date}`
      )
      return data
    } catch (error) {
      this.handleRepositoryError('getAvailability', error)
    }
  }

  override async create(payload: CreateBookingRequestDTO): Promise<Appointment> {
    return await super.create(payload)
  }

  async confirm(id: string): Promise<void> {
    try {
      await this.client.patch(`/appointments/${id}/confirm`)
    } catch (error) {
      this.handleRepositoryError('confirm', error)
    }
  }

  async complete(id: string): Promise<void> {
    try {
      await this.client.patch(`/appointments/${id}/complete`)
    } catch (error) {
      this.handleRepositoryError('complete', error)
    }
  }

  async cancel(id: string): Promise<void> {
    try {
      await this.client.patch(`/appointments/${id}/cancel`)
    } catch (error) {
      this.handleRepositoryError('cancel', error)
    }
  }

  async release(id: string): Promise<void> {
    try {
      await this.client.patch(`/appointments/${id}/release`)
    } catch (error) {
      this.handleRepositoryError('release', error)
    }
  }

  async markAbsent(id: string): Promise<void> {
    try {
      await this.client.patch(`/appointments/${id}/absent`)
    } catch (error) {
      this.handleRepositoryError('markAbsent', error)
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
      this.handleRepositoryError('reschedule', error)
    }
  }

  // --- Implementación de Hooks de CRUD (BaseRepository stubs) ---

  protected async createImpl(payload: CreateBookingRequestDTO): Promise<Appointment> {
    const { data } = await this.client.post<AppointmentResponseDTO>('/public/appointments', payload)
    return BookingMapper.toDomain(data)
  }

  protected async findAllImpl(options?: QueryOptions | boolean): Promise<Appointment[]> {
    // Tenia el mismo desfasaje de argumentos que searchByDateRange: pasaba
    // `page` como tercer parametro cuando la firma no lo declara. El rango va
    // en dias argentinos: `toISOString()` da el dia UTC, que de 21:00 a 23:59
    // ya es el siguiente (F10-10).
    const now = new Date()
    const { appointments: todas } = await this.searchByDateRange(
      formatArgentinaDate(subDays(now, 30).toISOString()),
      formatArgentinaDate(now.toISOString())
    )

    if (typeof options !== 'object' || !options) return todas
    const offset = options.offset ?? 0
    return options.limit ? todas.slice(offset, offset + options.limit) : todas.slice(offset)
  }

  protected async findByIdImpl(id: string): Promise<Appointment | null> {
    const { data } = await this.client.get('/appointments/search', {
      params: {
        page: 1,
        page_size: 100
      }
    })
    const found = (data.results || []).find((item: AppointmentResponseDTO) => item.public_id === id)
    return found ? BookingMapper.toDomain(found) : null
  }

  protected async updateImpl(id: string, data: BookingUpdatePayload): Promise<Appointment> {
    if (data?.notes_staff) {
      await this.client.patch(`/appointments/${id}/notes-staff`, { notes_staff: data.notes_staff })
    }
    const refreshed = await this.findByIdImpl(id)
    if (!refreshed) {
      throw new Error('Turno no encontrado')
    }
    return refreshed
  }

  protected async deleteImpl(id: string): Promise<void> {
    await this.cancel(id)
  }
}
