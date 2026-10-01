import { BookingMapper } from './BookingMapper'
import type { AppointmentResponseDTO } from '../dtos/BookingDTO'

// Cobertura de F9-08 (2026-09-30): el mapper no tenia test propio. Tests solo
// de cobertura, verdes desde el principio: describen el comportamiento actual.

// Sin staff_name ni client_phone: los dos son opcionales en el DTO.
const sinOpcionales: AppointmentResponseDTO = {
  public_id: 'apt-1',
  service_id: 'svc-1',
  service_name: 'Corte',
  staff_id: 'st-1',
  client_name: 'Juan',
  starts_at: '2026-10-01T13:00:00.000Z',
  ends_at: '2026-10-01T13:45:00.000Z',
  status: 'confirmed',
  notes: 'Trae foto'
}

const dto: AppointmentResponseDTO = {
  ...sinOpcionales,
  staff_name: 'Ana Perez',
  client_phone: '+5491100000000'
}

describe('BookingMapper.toDomain', () => {
  it('mapea cada campo del DTO a la entidad', () => {
    const turno = BookingMapper.toDomain(dto)

    expect(turno.id).toBe('apt-1')
    expect(turno.serviceId).toBe('svc-1')
    expect(turno.serviceName).toBe('Corte')
    expect(turno.staffId).toBe('st-1')
    expect(turno.staffName).toBe('Ana Perez')
    expect(turno.clientName).toBe('Juan')
    expect(turno.clientPhone).toBe('+5491100000000')
    expect(turno.timeSpan.getDurationMinutes()).toBe(45)
    expect(turno.status).toBe('confirmed')
    expect(turno.notes).toBe('Trae foto')
  })

  it('staff_name y client_phone ausentes quedan en null', () => {
    const turno = BookingMapper.toDomain(sinOpcionales)

    expect(turno.staffName).toBeNull()
    expect(turno.clientPhone).toBeNull()
  })

  it('un estado que el front no conoce no lanza', () => {
    expect(BookingMapper.toDomain({ ...dto, status: 'estado_nuevo' }).status).toBe('estado_nuevo')
  })

  it('un rango invertido lanza INVALID_TIME_SPAN', () => {
    expect(() =>
      BookingMapper.toDomain({ ...dto, starts_at: dto.ends_at, ends_at: dto.starts_at })
    ).toThrow(expect.objectContaining({ code: 'INVALID_TIME_SPAN' }))
  })
})

describe('BookingMapper.toResponseDTO', () => {
  it('DTO -> entidad -> DTO es identidad', () => {
    expect(BookingMapper.toResponseDTO(BookingMapper.toDomain(dto))).toEqual(dto)
  })

  it('los opcionales ausentes y notes null vuelven como null', () => {
    const vuelta = BookingMapper.toResponseDTO(
      BookingMapper.toDomain({ ...sinOpcionales, notes: null })
    )

    expect(vuelta).toMatchObject({ staff_name: null, client_phone: null, notes: null })
  })

  it('las fechas vuelven en ISO UTC aunque lleguen con offset', () => {
    const vuelta = BookingMapper.toResponseDTO(
      BookingMapper.toDomain({
        ...dto,
        starts_at: '2026-10-01T10:00:00-03:00',
        ends_at: '2026-10-01T10:45:00-03:00'
      })
    )

    expect(vuelta.starts_at).toBe('2026-10-01T13:00:00.000Z')
    expect(vuelta.ends_at).toBe('2026-10-01T13:45:00.000Z')
  })
})
