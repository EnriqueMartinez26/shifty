import type { AxiosInstance } from 'axios'

import { HttpServiceRepository } from './HttpServiceRepository'
import type { ServiceResponseDTO } from '../../application/dtos/ServiceDTO'
import { ServiceMapper } from '../../application/mappers/ServiceMapper'
import type { ServiceWriteInput } from '../../domain/entities/Service'
import { ConflictError } from '../../shared/errors/ConflictError'
import { NotFoundError } from '../../shared/errors/NotFoundError'

const serviceConSena: ServiceResponseDTO = {
  public_id: 'svc-1',
  name: 'Corte',
  description: 'Corte de pelo',
  duration_minutes: 30,
  price: 10000,
  color: '#3b82f6',
  image_url: null,
  youtube_trailer_url: null,
  deposit_mode: 'required',
  deposit_type: 'percent',
  deposit_amount: 50,
  is_active: true
}

type WriteBody = Record<string, unknown>
type WriteCall = jest.Mock<Promise<{ data: ServiceResponseDTO }>, [string, WriteBody]>

/**
 * Doble del cliente axios: solo interesa QUE CUERPO sale hacia la API.
 */
const createClient = () => {
  const patch: WriteCall = jest.fn()
  const post: WriteCall = jest.fn()
  patch.mockResolvedValue({ data: serviceConSena })
  post.mockResolvedValue({ data: serviceConSena })

  const client = {
    get: jest.fn(),
    post,
    patch,
    delete: jest.fn()
  }

  return {
    patch,
    post,
    repository: new HttpServiceRepository(client as unknown as AxiosInstance)
  }
}

const bodyOf = (call: WriteCall): WriteBody => {
  const primera = call.mock.calls[0]
  // Si no hubo llamada, el test tiene que fallar diciendo eso y no con un
  // "cannot read property of undefined" diez lineas mas abajo.
  if (!primera) throw new Error('el repositorio no llamo al cliente HTTP')
  return primera[1]
}

describe('HttpServiceRepository — politica de sena (F10-03 / F9-06)', () => {
  it('editar el nombre de un servicio con sena configurada NO la apaga', async () => {
    const { patch, repository } = createClient()

    // Lo que hace el formulario al editar: carga los valores REALES del
    // servicio, el dueño cambia solo el nombre y guarda.
    const cargadoEnElFormulario: ServiceWriteInput = {
      name: 'Corte premium',
      description: 'Corte de pelo',
      durationMinutes: 30,
      price: 10000,
      color: '#3b82f6',
      imageUrl: null,
      youtubeTrailerUrl: null,
      depositMode: 'required',
      depositType: 'percent',
      depositAmount: 50
    }

    await repository.update('svc-1', cargadoEnElFormulario)

    expect(bodyOf(patch)).toMatchObject({
      name: 'Corte premium',
      deposit_mode: 'required',
      deposit_type: 'percent',
      deposit_amount: 50
    })
  })

  it('un PATCH que no menciona la sena no manda ningun campo de sena', async () => {
    const { patch, repository } = createClient()

    await repository.update('svc-1', { name: 'Solo el nombre' })

    const body = bodyOf(patch)
    expect(body).toEqual({ name: 'Solo el nombre' })
    expect(body).not.toHaveProperty('deposit_mode')
    expect(body).not.toHaveProperty('deposit_type')
    expect(body).not.toHaveProperty('deposit_amount')
  })

  it('el PATCH nunca inventa `deposit_mode: none` por omision', async () => {
    const { patch, repository } = createClient()

    await repository.update('svc-1', { price: 12000 })

    expect(bodyOf(patch)).toEqual({ price: 12000 })
  })

  it('un PATCH puede apagar la sena, pero solo si lo pide explicitamente', async () => {
    const { patch, repository } = createClient()

    await repository.update('svc-1', { depositMode: 'none' })

    expect(bodyOf(patch)).toEqual({ deposit_mode: 'none' })
  })

  it('`is_active` viaja solo en el PATCH y solo si viene definido', async () => {
    const { patch, repository } = createClient()

    await repository.update('svc-1', { isActive: false })

    expect(bodyOf(patch)).toEqual({ is_active: false })
  })

  it('el POST manda la politica de sena del servicio nuevo y no manda `is_active`', async () => {
    const { post, repository } = createClient()

    const nuevo = ServiceMapper.toDomain({
      ...serviceConSena,
      deposit_mode: 'optional',
      deposit_type: 'fixed',
      deposit_amount: 3000
    })

    await repository.create(nuevo)

    const body = bodyOf(post)
    expect(body).toMatchObject({
      name: 'Corte',
      duration_minutes: 30,
      price: 10000,
      deposit_mode: 'optional',
      deposit_type: 'fixed',
      deposit_amount: 3000
    })
    expect(body).not.toHaveProperty('is_active')
  })

  it('un servicio sin sena viaja con los defaults del backend', async () => {
    const { post, repository } = createClient()

    const sinSena = ServiceMapper.toDomain({
      ...serviceConSena,
      deposit_mode: 'none',
      deposit_type: 'percent',
      deposit_amount: null
    })

    await repository.create(sinSena)

    expect(bodyOf(post)).toMatchObject({
      deposit_mode: 'none',
      deposit_type: 'percent',
      deposit_amount: null
    })
  })
})

/**
 * FF-35 (2026-09-28): el cliente HTTP ya entrega un 404 como NotFoundError, sin
 * `response`; la rama `response?.status === 404` nunca corria y el 404 salia
 * como error en vez de `null`.
 */
describe('HttpServiceRepository.findById ante un 404', () => {
  const setup = () => {
    const get = jest.fn()
    const client = { get, post: jest.fn(), patch: jest.fn(), put: jest.fn(), delete: jest.fn() }
    return { get, repository: new HttpServiceRepository(client as unknown as AxiosInstance) }
  }

  it('devuelve null, no un error', async () => {
    const { get, repository } = setup()
    get.mockRejectedValue(new NotFoundError('x', { statusCode: 404 }))

    await expect(repository.findById('svc-x')).resolves.toBeNull()
  })

  it('deja pasar tal cual cualquier otro error de aplicacion', async () => {
    const { get, repository } = setup()
    const conflicto = new ConflictError('choque')
    get.mockRejectedValue(conflicto)

    await expect(repository.findById('svc-x')).rejects.toBe(conflicto)
  })
})

/**
 * FF-22 (2026-09-30): un servicio eliminado o desactivado desaparecia del panel
 * y no se podia reactivar. `include_inactive` exige STORE_MANAGERS en el
 * backend (403 a un profesional), asi que viaja SOLO cuando se pide.
 */
describe('HttpServiceRepository.findAll e include_inactive', () => {
  const setup = () => {
    const get = jest.fn().mockResolvedValue({ data: [serviceConSena] })
    const client = { get, post: jest.fn(), patch: jest.fn(), delete: jest.fn() }
    return { get, repository: new HttpServiceRepository(client as unknown as AxiosInstance) }
  }

  it('la lista compartida no manda ningun parametro', async () => {
    const { get, repository } = setup()

    await repository.findAll()

    expect(get.mock.calls).toEqual([['/services/']])
  })

  it('el catalogo pide los inactivos con include_inactive=true', async () => {
    const { get, repository } = setup()

    await repository.findAll({ includeInactive: true })

    expect(get.mock.calls).toEqual([['/services/', { params: { include_inactive: true } }]])
  })

  it('acepta el booleano de la interfaz, como HttpUserRepository', async () => {
    const { get, repository } = setup()

    await repository.findAll(true)
    await repository.findAll(false)

    expect(get.mock.calls).toEqual([
      ['/services/', { params: { include_inactive: true } }],
      ['/services/']
    ])
  })

  it('reactivar manda solo `is_active: true`', async () => {
    const { patch, repository } = createClient()

    await repository.update('svc-1', { isActive: true })

    expect(bodyOf(patch)).toEqual({ is_active: true })
  })
})

/**
 * 2026-09-30: el panel no podia subir la imagen de un servicio aunque el
 * backend ya lo permitia (POST y DELETE /services/{id}/image).
 */
describe('HttpServiceRepository — imagen del servicio', () => {
  const conImagen: ServiceResponseDTO = {
    ...serviceConSena,
    image_url: 'https://app.test/api/stores/media/nueva'
  }
  const setup = () => {
    const post = jest.fn().mockResolvedValue({ data: conImagen })
    const del = jest.fn().mockResolvedValue({ data: serviceConSena })
    const client = { get: jest.fn(), post, patch: jest.fn(), delete: del }
    return { post, del, repository: new HttpServiceRepository(client as unknown as AxiosInstance) }
  }

  it('sube el archivo como multipart en el campo `file`, sin `kind`', async () => {
    const { post, repository } = setup()
    const archivo = new Blob([new Uint8Array([0x89, 0x50])], { type: 'image/png' })

    const actualizado = await repository.uploadImage('svc-1', archivo)

    expect(post).toHaveBeenCalledTimes(1)
    const [ruta, form, config] = post.mock.calls[0] as [string, FormData, unknown]
    expect(ruta).toBe('/services/svc-1/image')
    expect(form).toBeInstanceOf(FormData)
    expect([...form.keys()]).toEqual(['file'])
    expect(form.get('file')).toBeInstanceOf(Blob)
    expect(config).toEqual({ headers: { 'Content-Type': 'multipart/form-data' } })
    expect(actualizado.imageUrl).toBe('https://app.test/api/stores/media/nueva')
  })

  it('quitar la imagen llama a DELETE y devuelve el servicio actualizado', async () => {
    const { del, repository } = setup()

    const actualizado = await repository.removeImage('svc-1')

    expect(del.mock.calls).toEqual([['/services/svc-1/image']])
    expect(actualizado.imageUrl).toBeNull()
  })

  it('un error de la API sale como error de aplicacion tipado', async () => {
    const { post, repository } = setup()
    const conflicto = new ConflictError('choque')
    post.mockRejectedValue(conflicto)

    await expect(repository.uploadImage('svc-1', new Blob(['x']))).rejects.toBe(conflicto)
  })
})
