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
      delete: jest.fn(),
      uploadImage: jest.fn(),
      removeImage: jest.fn()
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

  it('un porcentaje mayor a 100 se rechaza en el cliente (D-20260930-09)', async () => {
    // D-20260930-09 (2026-10-01): el alta dejaba pasar 150% y el backend lo
    // rechaza ("un porcentaje de sena no puede superar 100"), igual que la
    // base (ck_services_deposit_percent_max): el formulario rechaza lo mismo.
    const promise = service.createService({
      ...BASE_INPUT,
      depositMode: 'required',
      depositType: 'percent',
      depositAmount: 150
    })

    const error: unknown = await promise.catch((caught: unknown) => caught)
    expect((error as ValidationDetails).details).toEqual([
      { path: 'deposit_amount', message: 'El porcentaje de la seña no puede superar 100' }
    ])
    expect(mockRepository.create).not.toHaveBeenCalled()
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

  it('updateService rechaza un porcentaje mayor a 100 sin llamar al repositorio (D-20260930-09)', async () => {
    // D-20260930-09 (2026-10-01): la edicion no validaba en el cliente y el
    // PATCH con 150% salia para volver con 422.
    const promise = service.updateService('svc-1', {
      depositMode: 'required',
      depositType: 'percent',
      depositAmount: 150
    })

    const error: unknown = await promise.catch((caught: unknown) => caught)
    expect((error as ValidationDetails).details).toEqual([
      { path: 'deposit_amount', message: 'El porcentaje de la seña no puede superar 100' }
    ])
    expect(mockRepository.update).not.toHaveBeenCalled()
  })

  it('updateService deja pasar un PATCH parcial y el null que borra', async () => {
    mockRepository.update.mockResolvedValue(await service.createService(BASE_INPUT))

    await service.updateService('svc-1', { isActive: true })
    await service.updateService('svc-1', { description: null, depositAmount: null })

    expect(mockRepository.update).toHaveBeenNthCalledWith(1, 'svc-1', { isActive: true })
    expect(mockRepository.update).toHaveBeenNthCalledWith(2, 'svc-1', {
      description: null,
      depositAmount: null
    })
  })
})

/**
 * FF-22 (2026-09-30): un servicio eliminado o desactivado desaparecia del panel
 * y no se podia reactivar.
 */
describe('ServiceService — catalogo con inactivos', () => {
  const setup = () => {
    const mockRepository = {
      findAll: jest.fn().mockResolvedValue([]),
      findById: jest.fn(),
      create: jest.fn(),
      update: jest.fn(),
      delete: jest.fn(),
      uploadImage: jest.fn(),
      removeImage: jest.fn()
    } as jest.Mocked<IServiceRepository>
    return { mockRepository, service: new ServiceService(mockRepository) }
  }

  it('listCatalog pide los inactivos', async () => {
    const { mockRepository, service } = setup()

    await service.listCatalog()

    expect(mockRepository.findAll).toHaveBeenCalledWith({ includeInactive: true })
  })

  it('listServices sigue pidiendo solo los activos', async () => {
    const { mockRepository, service } = setup()

    await service.listServices()

    expect(mockRepository.findAll).toHaveBeenCalledWith()
  })
})

/**
 * 2026-09-30: el panel no podia subir la imagen de un servicio aunque el
 * backend ya lo permitia.
 */
describe('ServiceService — imagen del servicio', () => {
  const setup = () => {
    const mockRepository = {
      findAll: jest.fn(),
      findById: jest.fn(),
      create: jest.fn(),
      update: jest.fn(),
      delete: jest.fn(),
      uploadImage: jest.fn(),
      removeImage: jest.fn()
    } as jest.Mocked<IServiceRepository>
    return { mockRepository, service: new ServiceService(mockRepository) }
  }

  it('uploadImage delega en el repositorio y devuelve el servicio actualizado', async () => {
    const { mockRepository, service } = setup()
    const archivo = new Blob(['x'], { type: 'image/png' })
    const actualizado = { id: 'svc-1' } as Awaited<ReturnType<IServiceRepository['uploadImage']>>
    mockRepository.uploadImage.mockResolvedValue(actualizado)

    await expect(service.uploadImage('svc-1', archivo)).resolves.toBe(actualizado)
    expect(mockRepository.uploadImage).toHaveBeenCalledWith('svc-1', archivo)
  })

  it('removeImage delega en el repositorio', async () => {
    const { mockRepository, service } = setup()
    const actualizado = { id: 'svc-1' } as Awaited<ReturnType<IServiceRepository['removeImage']>>
    mockRepository.removeImage.mockResolvedValue(actualizado)

    await expect(service.removeImage('svc-1')).resolves.toBe(actualizado)
    expect(mockRepository.removeImage).toHaveBeenCalledWith('svc-1')
  })
})
