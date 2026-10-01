import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { act, renderHook, waitFor } from '@testing-library/react'

import {
  useCreateManagedService,
  useManagedServiceCatalog,
  useManagedServices,
  useRemoveServiceImage,
  useUpdateManagedService,
  useUploadServiceImage
} from './useManagedServices'

const mockListServices = jest.fn()
const mockListCatalog = jest.fn()
const mockCreateService = jest.fn()
const mockUpdateService = jest.fn()
const mockUploadImage = jest.fn()
const mockRemoveImage = jest.fn()

jest.mock('@application/services/ServiceService', () => ({
  serviceService: {
    listServices: () => mockListServices(),
    listCatalog: () => mockListCatalog(),
    createService: (...args: unknown[]) => mockCreateService(...args),
    updateService: (...args: unknown[]) => mockUpdateService(...args),
    uploadImage: (...args: unknown[]) => mockUploadImage(...args),
    removeImage: (...args: unknown[]) => mockRemoveImage(...args)
  }
}))

const envoltorio = ({ children }: { children: React.ReactNode }) => {
  const queryClient = new QueryClient({
    defaultOptions: { mutations: { retry: false }, queries: { retry: false } }
  })
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
}

describe('useManagedServices', () => {
  it('dar de alta un servicio refresca la lista que leen el alta de profesionales y los links', async () => {
    // F11c-10: StaffFormModal y ShareLinksPanel leian `['services']` con una
    // copia literal de este hook. Ahora usan este mismo, asi que la
    // invalidacion de las mutaciones de al lado es la que los mantiene al dia.
    mockListServices.mockResolvedValue([])
    mockCreateService.mockResolvedValue({ id: 'svc_1' })

    const { result } = renderHook(
      () => ({ lista: useManagedServices(), alta: useCreateManagedService() }),
      { wrapper: envoltorio }
    )
    await waitFor(() => expect(result.current.lista.isSuccess).toBe(true))
    expect(mockListServices).toHaveBeenCalledTimes(1)

    await act(() =>
      result.current.alta.mutateAsync({ name: 'Corte' } as Parameters<
        typeof result.current.alta.mutateAsync
      >[0])
    )

    await waitFor(() => expect(mockListServices).toHaveBeenCalledTimes(2))
  })
})

/**
 * FF-22 (2026-09-30): un servicio eliminado o desactivado desaparecia del panel
 * y no se podia reactivar. El catalogo va en su propia clave para que la lista
 * compartida (`['services']`: alta de turno, profesionales, links) siga viendo
 * solo los activos.
 */
describe('useManagedServiceCatalog', () => {
  const setup = () => {
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false }, queries: { retry: false } }
    })
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
    return { queryClient, wrapper }
  }

  beforeEach(() => {
    mockListServices.mockReset().mockResolvedValue([])
    mockListCatalog.mockReset().mockResolvedValue([])
    mockUpdateService.mockReset().mockResolvedValue({ id: 'svc-1' })
  })

  it('lee el catalogo con inactivos bajo su clave, aparte de la lista compartida', async () => {
    const { queryClient, wrapper } = setup()

    const { result } = renderHook(
      () => ({ catalogo: useManagedServiceCatalog(), lista: useManagedServices() }),
      { wrapper }
    )
    await waitFor(() => expect(result.current.catalogo.isSuccess).toBe(true))
    await waitFor(() => expect(result.current.lista.isSuccess).toBe(true))

    expect(mockListCatalog).toHaveBeenCalledTimes(1)
    expect(mockListServices).toHaveBeenCalledTimes(1)
    expect(queryClient.getQueryState(['services', 'catalog'])?.status).toBe('success')
  })

  it('reactivar refresca el catalogo: la invalidacion de `services` lo alcanza', async () => {
    const { wrapper } = setup()

    const { result } = renderHook(
      () => ({ catalogo: useManagedServiceCatalog(), edicion: useUpdateManagedService() }),
      { wrapper }
    )
    await waitFor(() => expect(result.current.catalogo.isSuccess).toBe(true))

    await act(() => result.current.edicion.mutateAsync({ id: 'svc-1', data: { isActive: true } }))

    expect(mockUpdateService).toHaveBeenCalledWith('svc-1', { isActive: true })
    await waitFor(() => expect(mockListCatalog).toHaveBeenCalledTimes(2))
  })
})

/**
 * 2026-09-30: el panel no podia subir la imagen de un servicio aunque el
 * backend ya lo permitia. Subir y quitar persisten al instante, asi que las dos
 * mutaciones refrescan el prefijo `['services']` (catalogo y lista compartida).
 */
describe('imagen del servicio', () => {
  const setup = () => {
    const queryClient = new QueryClient({
      defaultOptions: { mutations: { retry: false }, queries: { retry: false } }
    })
    const invalidar = jest.spyOn(queryClient, 'invalidateQueries')
    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    )
    return { invalidar, wrapper }
  }

  beforeEach(() => {
    mockUploadImage.mockReset().mockResolvedValue({ id: 'svc-1' })
    mockRemoveImage.mockReset().mockResolvedValue({ id: 'svc-1' })
  })

  it('subir la imagen invalida `services`', async () => {
    const { invalidar, wrapper } = setup()
    const archivo = new Blob(['x'], { type: 'image/png' })

    const { result } = renderHook(() => useUploadServiceImage(), { wrapper })
    await act(() => result.current.mutateAsync({ id: 'svc-1', file: archivo }))

    expect(mockUploadImage).toHaveBeenCalledWith('svc-1', archivo)
    expect(invalidar).toHaveBeenCalledWith({ queryKey: ['services'] })
  })

  it('quitar la imagen invalida `services`', async () => {
    const { invalidar, wrapper } = setup()

    const { result } = renderHook(() => useRemoveServiceImage(), { wrapper })
    await act(() => result.current.mutateAsync('svc-1'))

    expect(mockRemoveImage).toHaveBeenCalledWith('svc-1')
    expect(invalidar).toHaveBeenCalledWith({ queryKey: ['services'] })
  })
})
