// El singleton `serviceService` exportado por ServiceService.ts importa el
// apiClient real (que a su vez toca runtime-env.ts / import.meta, que ts-jest
// no compila fuera de node_modules). Se mockea el módulo del cliente HTTP para
// poder cargar la clase bajo test sin arrastrar esa cadena.
jest.mock('../../infrastructure/http/client', () => ({
  __esModule: true,
  default: {}
}))

import { ServiceService } from './ServiceService'
import type { IServiceRepository } from '../../domain/repositories/IServiceRepository'

interface ValidationDetails {
  details?: Array<{ path: string; message: string }>
}

const BASE_INPUT = {
  name: 'Corte de pelo',
  durationMinutes: 30,
  price: 10000
}

describe('ServiceService — politica de sena (F10-03 / F9-06)', () => {
  let mockRepository: jest.Mocked<IServiceRepository>
  let service: ServiceService

  beforeEach(() => {
    mockRepository = {
      findAll: jest.fn(),
      findById: jest.fn(),
      create: jest.fn(),
      update: jest.fn(),
      delete: jest.fn()
    } as jest.Mocked<IServiceRepository>

    mockRepository.create.mockImplementation(async (created) => created)
    service = new ServiceService(mockRepository)
  })

  it('crear un servicio con sena obligatoria manda los tres campos', async () => {
    const result = await service.createService({
      ...BASE_INPUT,
      depositMode: 'required',
      depositType: 'percent',
      depositAmount: 50
    })

    expect(result.toPrimitives()).toMatchObject({
      deposit_mode: 'required',
      deposit_type: 'percent',
      deposit_amount: 50
    })
  })

  it('crear un servicio sin sena usa los defaults del backend', async () => {
    const result = await service.createService(BASE_INPUT)

    expect(result.toPrimitives()).toMatchObject({
      deposit_mode: 'none',
      deposit_type: 'percent',
      deposit_amount: null
    })
  })

  it('`full` con monto nulo es una combinacion valida: full ya es el 100%', async () => {
    const result = await service.createService({
      ...BASE_INPUT,
      depositMode: 'required',
      depositType: 'full',
      depositAmount: null
    })

    expect(result.toPrimitives()).toMatchObject({
      deposit_mode: 'required',
      deposit_type: 'full',
      deposit_amount: null
    })
  })

  it('`percent` sin monto se rechaza con un mensaje en espanol', async () => {
    const promise = service.createService({
      ...BASE_INPUT,
      depositMode: 'required',
      depositType: 'percent',
      depositAmount: null
    })

    await expect(promise).rejects.toThrow('Error de validación')

    const error: unknown = await promise.catch((caught: unknown) => caught)
    expect((error as ValidationDetails).details).toEqual([
      { path: 'deposit_amount', message: 'Indicá el porcentaje de la seña' }
    ])
    expect(mockRepository.create).not.toHaveBeenCalled()
  })

  it('`fixed` sin monto se rechaza con su propio mensaje', async () => {
    const promise = service.createService({
      ...BASE_INPUT,
      depositMode: 'optional',
      depositType: 'fixed'
    })

    const error: unknown = await promise.catch((caught: unknown) => caught)
    expect((error as ValidationDetails).details).toEqual([
      { path: 'deposit_amount', message: 'Indicá el monto fijo de la seña' }
    ])
    expect(mockRepository.create).not.toHaveBeenCalled()
  })

  it('un porcentaje mayor a 100 NO se rechaza en el cliente', async () => {
    // A proposito: el backend acepta hasta 10.000.000 para cualquier tipo, y un
    // cliente mas estricto que el contrato deja datos legitimos imposibles de
    // editar (un servicio con 500% cargado por otra via no se podria ni
    // renombrar). Si el tope del 100% se quiere como regla de negocio, va en el
    // backend, donde tambien protege a la API (2026-09-21).
    await service.createService({
      ...BASE_INPUT,
      depositMode: 'required',
      depositType: 'percent',
      depositAmount: 150
    })

    expect(mockRepository.create).toHaveBeenCalledTimes(1)
  })

  it('sin sena el monto no se exige aunque el tipo sea `percent`', async () => {
    const result = await service.createService({
      ...BASE_INPUT,
      depositMode: 'none',
      depositType: 'percent',
      depositAmount: null
    })

    expect(result.toPrimitives()).toMatchObject({ deposit_mode: 'none', deposit_amount: null })
    expect(mockRepository.create).toHaveBeenCalledTimes(1)
  })

  it('updateService no completa la sena por su cuenta: pasa el payload tal cual', async () => {
    const existente = await service.createService(BASE_INPUT)
    mockRepository.update.mockResolvedValue(existente)

    await service.updateService('svc-1', { name: 'Otro nombre' })

    expect(mockRepository.update).toHaveBeenCalledWith('svc-1', { name: 'Otro nombre' })
  })
})
