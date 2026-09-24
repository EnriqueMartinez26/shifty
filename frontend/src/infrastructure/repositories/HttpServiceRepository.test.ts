import type { AxiosInstance } from 'axios'

import { HttpServiceRepository } from './HttpServiceRepository'
import type { ServiceResponseDTO } from '../../application/dtos/ServiceDTO'
import { ServiceMapper } from '../../application/mappers/ServiceMapper'
import type { ServiceWriteInput } from '../../domain/entities/Service'

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
