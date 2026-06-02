import type { AxiosInstance } from 'axios';
import { Appointment } from '../../domain/entities/Appointment';
import { BaseRepository } from './BaseRepository';
import type { IBookingRepository } from '../../domain/repositories/IBookingRepository';
import type { AppointmentResponseDTO, CreateBookingRequestDTO } from '../../application/dtos/BookingDTO';
import { BookingMapper } from '../../application/mappers/BookingMapper';
import { QueryOptions } from '../../domain/repositories/IRepository';

export class HttpBookingRepository 
  extends BaseRepository<Appointment, CreateBookingRequestDTO, any>
  implements IBookingRepository 
{
  private client: AxiosInstance;

  constructor(client: AxiosInstance) {
    super();
    this.client = client;
  }

  async findByDate(date: string): Promise<Appointment[]> {
    try {
      const { data } = await this.client.get<AppointmentResponseDTO[]>(`/appointments/?date=${date}`);
      return data.map(BookingMapper.toDomain);
    } catch (error) {
      this.handleRepositoryError('findByDate', error);
    }
  }

  async getAvailability(serviceId: string, date: string): Promise<any> {
    try {
      const { data } = await this.client.get(`/appointments/availability?service_id=${serviceId}&date=${date}`);
      return data;
    } catch (error) {
      this.handleRepositoryError('getAvailability', error);
    }
  }

  async create(payload: CreateBookingRequestDTO): Promise<Appointment> {
    return await super.create(payload);
  }

  async confirm(id: string): Promise<void> {
    try {
      await this.client.patch(`/appointments/${id}/confirm`);
    } catch (error) {
      this.handleRepositoryError('confirm', error);
    }
  }

  async complete(id: string): Promise<void> {
    try {
      await this.client.patch(`/appointments/${id}/complete`);
    } catch (error) {
      this.handleRepositoryError('complete', error);
    }
  }

  async cancel(id: string): Promise<void> {
    try {
      await this.client.patch(`/appointments/${id}/cancel`);
    } catch (error) {
      this.handleRepositoryError('cancel', error);
    }
  }

  async markAbsent(id: string): Promise<void> {
    try {
      await this.client.patch(`/appointments/${id}/absent`);
    } catch (error) {
      this.handleRepositoryError('markAbsent', error);
    }
  }

  // --- Implementación de Hooks de CRUD (BaseRepository stubs) ---

  protected async createImpl(payload: CreateBookingRequestDTO): Promise<Appointment> {
    const { data } = await this.client.post<AppointmentResponseDTO>('/public/appointments', payload);
    return BookingMapper.toDomain(data);
  }

  protected async findAllImpl(options?: QueryOptions | boolean): Promise<Appointment[]> {
    const pageSize = typeof options === 'object' && options?.limit ? options.limit : 100;
    const page = typeof options === 'object' && options?.offset ? Math.floor(options.offset / pageSize) + 1 : 1;
    const fromDate = new Date();
    fromDate.setDate(fromDate.getDate() - 30);
    const toDate = new Date();

    const { data } = await this.client.get('/appointments/search', {
      params: {
        from_date: fromDate.toISOString().slice(0, 10),
        to_date: toDate.toISOString().slice(0, 10),
        page,
        page_size: pageSize,
      },
    });
    return (data.results || []).map(BookingMapper.toDomain);
  }

  protected async findByIdImpl(id: string): Promise<Appointment | null> {
    const { data } = await this.client.get('/appointments/search', {
      params: {
        page: 1,
        page_size: 100,
      },
    });
    const found = (data.results || []).find((item: AppointmentResponseDTO) => item.public_id === id);
    return found ? BookingMapper.toDomain(found) : null;
  }

  protected async updateImpl(id: string, data: any): Promise<Appointment> {
    if (data?.notes_staff) {
      await this.client.patch(`/appointments/${id}/notes-staff`, { notes_staff: data.notes_staff });
    }
    const refreshed = await this.findByIdImpl(id);
    if (!refreshed) {
      throw new Error('Turno no encontrado');
    }
    return refreshed;
  }

  protected async deleteImpl(id: string): Promise<void> {
    await this.cancel(id);
  }
}
export default HttpBookingRepository;
