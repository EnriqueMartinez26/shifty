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
  is_active: true,
  requires_prior_design: true,
  prior_design_message: 'Traé tu diseño',
  addons: [
    { id: 'add-1', name: 'Strass', unit_price: 500, max_quantity: 10, position: 0 },
    { id: 'add-2', name: 'Diseño', unit_price: 1500.5, max_quantity: 2, position: 1 }
  ]
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

describe('ServiceMapper: adicionales', () => {
  it('manda el conjunto entero en snake_case, sin id ni posicion y con el nombre recortado', () => {
    expect(
      ServiceMapper.toWritePayload({
        addons: [
          { name: ' Strass ', unitPrice: 500, maxQuantity: 10 },
          { name: 'Diseño', unitPrice: 1500, maxQuantity: 2 }
        ]
      })
    ).toEqual({
      addons: [
        { name: 'Strass', unit_price: 500, max_quantity: 10 },
        { name: 'Diseño', unit_price: 1500, max_quantity: 2 }
      ]
    })
  })

  it('una lista vacia viaja (borra los adicionales); ausente no viaja', () => {
    expect(ServiceMapper.toWritePayload({ addons: [] })).toEqual({ addons: [] })
    expect(ServiceMapper.toWritePayload({ name: 'Corte' })).toEqual({ name: 'Corte' })
  })

  it('un DTO sin adicionales da un servicio sin adicionales', () => {
    expect(ServiceMapper.toDomain({ ...dto, addons: undefined }).addons).toEqual([])
  })
})

describe('ServiceMapper: id de los adicionales', () => {
  it('manda el id de los que ya existen y omite el de los nuevos', () => {
    expect(
      ServiceMapper.toWritePayload({
        addons: [
          { id: 'add-1', name: 'Strass', unitPrice: 500, maxQuantity: 10 },
          { id: null, name: 'Diseño', unitPrice: 1500, maxQuantity: 2 }
        ]
      })
    ).toEqual({
      addons: [
        { id: 'add-1', name: 'Strass', unit_price: 500, max_quantity: 10 },
        { name: 'Diseño', unit_price: 1500, max_quantity: 2 }
      ]
    })
  })

  it('un servicio guardado manda los ids de sus adicionales', () => {
    expect(ServiceMapper.toWritePayload(ServiceMapper.toDomain(dto)).addons).toEqual([
      { id: 'add-1', name: 'Strass', unit_price: 500, max_quantity: 10 },
      { id: 'add-2', name: 'Diseño', unit_price: 1500.5, max_quantity: 2 }
    ])
  })
})

describe('ServiceMapper: diseño previo (S7)', () => {
  it('un DTO sin los campos (backend anterior) no pide diseño previo', () => {
    // Un backend anterior al diseño previo no manda los campos.
    const viejo = { ...dto, requires_prior_design: undefined, prior_design_message: undefined }
    const service = ServiceMapper.toDomain(viejo)

    expect(service.requiresPriorDesign).toBe(false)
    expect(service.priorDesignMessage).toBeNull()
  })

  it('viajan en snake_case y el mensaje va recortado', () => {
    expect(
      ServiceMapper.toWritePayload({
        requiresPriorDesign: true,
        priorDesignMessage: '  Mandá tu diseño  '
      })
    ).toEqual({ requires_prior_design: true, prior_design_message: 'Mandá tu diseño' })
  })

  it('un mensaje vacio viaja como null (lo borra)', () => {
    expect(ServiceMapper.toWritePayload({ priorDesignMessage: '   ' })).toEqual({
      prior_design_message: null
    })
  })

  it('ausentes no viajan', () => {
    expect(ServiceMapper.toWritePayload({ name: 'Corte' })).toEqual({ name: 'Corte' })
  })
})
