import { ServiceMapper } from './ServiceMapper'
import { Duration } from '../../domain/value-objects/Duration'
import { Price } from '../../domain/value-objects/Price'
import type { ServiceResponseDTO } from '../dtos/ServiceDTO'

// Cobertura de F9-08 (2026-09-30): el mapper solo se usaba de costado en
// HttpServiceRepository.test.ts. Tests solo de cobertura, verdes desde el
// principio: describen el comportamiento actual.

const dto: ServiceResponseDTO = {
  public_id: 'svc-1',
  name: 'Corte',
  description: 'Corte clasico',
  duration_minutes: 45,
  price: 12000,
  color: '#AABBCC',
  image_url: 'https://x.com/corte.png',
  youtube_trailer_url: 'https://youtu.be/abc',
  deposit_mode: 'required',
  deposit_type: 'fixed',
  deposit_amount: 3000,
  is_active: true
}

describe('ServiceMapper.toDomain', () => {
  it('mapea cada campo del DTO a la entidad', () => {
    const service = ServiceMapper.toDomain(dto)

    expect(service.id).toBe('svc-1')
    expect(service.name).toBe('Corte')
    expect(service.description).toBe('Corte clasico')
    expect(service.duration.getValue()).toBe(45)
    expect(service.price.getValue()).toBe(12000)
    expect(service.color).toBe('#AABBCC')
    expect(service.imageUrl).toBe('https://x.com/corte.png')
    expect(service.youtubeTrailerUrl).toBe('https://youtu.be/abc')
    expect(service.depositMode).toBe('required')
    expect(service.depositType).toBe('fixed')
    expect(service.depositAmount).toBe(3000)
    expect(service.isActive).toBe(true)
  })

  it('conserva los null de descripcion, medios y monto de sena', () => {
    const service = ServiceMapper.toDomain({
      ...dto,
      description: null,
      image_url: null,
      youtube_trailer_url: null,
      deposit_amount: null
    })

    expect(service.description).toBeNull()
    expect(service.imageUrl).toBeNull()
    expect(service.youtubeTrailerUrl).toBeNull()
    expect(service.depositAmount).toBeNull()
  })

  it('un color null toma el color por defecto de la entidad', () => {
    expect(ServiceMapper.toDomain({ ...dto, color: null }).color).toBe('#6366f1')
  })

  it('acepta el color de 3 digitos que devuelve el backend', () => {
    expect(ServiceMapper.toDomain({ ...dto, color: '#abc' }).color).toBe('#abc')
  })
})

describe('ServiceMapper.toResponseDTO', () => {
  it('DTO -> entidad -> DTO es identidad', () => {
    expect(ServiceMapper.toResponseDTO(ServiceMapper.toDomain(dto))).toEqual(dto)
  })

  it('los null vuelven como null salvo el color, que vuelve con el default', () => {
    const conNulls: ServiceResponseDTO = {
      ...dto,
      description: null,
      color: null,
      image_url: null,
      youtube_trailer_url: null,
      deposit_amount: null
    }

    expect(ServiceMapper.toResponseDTO(ServiceMapper.toDomain(conNulls))).toEqual({
      ...conNulls,
      color: '#6366f1'
    })
  })
})

describe('ServiceMapper.toWritePayload', () => {
  it('un input vacio produce un payload vacio', () => {
    expect(ServiceMapper.toWritePayload({})).toEqual({})
  })

  it('los value objects se mandan como numero', () => {
    expect(
      ServiceMapper.toWritePayload({ duration: Duration.create(30), price: Price.create(5000) })
    ).toEqual({ duration_minutes: 30, price: 5000 })
  })

  it('durationMinutes gana sobre duration', () => {
    const payload = ServiceMapper.toWritePayload({
      durationMinutes: 60,
      duration: Duration.create(30)
    })

    expect(payload).toEqual({ duration_minutes: 60 })
  })

  it('null viaja (borra el dato) y los nombres pasan a snake_case', () => {
    expect(
      ServiceMapper.toWritePayload({
        description: null,
        imageUrl: null,
        youtubeTrailerUrl: 'https://youtu.be/abc',
        color: '#abc',
        depositType: 'percent',
        depositAmount: null,
        isActive: false
      })
    ).toEqual({
      description: null,
      image_url: null,
      youtube_trailer_url: 'https://youtu.be/abc',
      color: '#abc',
      deposit_type: 'percent',
      deposit_amount: null
    })
  })
})
