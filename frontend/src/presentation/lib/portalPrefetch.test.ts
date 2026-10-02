import { createElement, type ReactNode } from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { renderHook, waitFor } from '@testing-library/react'

import { NotFoundError } from '@shared/errors'

import { prefetchPortal, type PortalLoaders } from './portalPrefetch'
import { usePublicServices, usePublicStore, usePublicStoreRef } from '../hooks/usePublic'
import { PUBLIC_ROUTES } from '../routes/appRoutes'

// F4-14 (2026-10-02): al abrir /b/:slug la app montaba, recien ahi pedia el
// chunk de PublicBooking y, cuando ese chunk cargaba, recien la tienda y
// despues los servicios: tres viajes en serie antes de ver el primer paso.

const mockGetStore = jest.fn()
const mockGetStoreRef = jest.fn()
const mockGetServices = jest.fn()

jest.mock('@application/services/PublicBookingService', () => ({
  publicBookingService: {
    getStore: (...args: unknown[]) => mockGetStore(...args),
    getStoreRef: (...args: unknown[]) => mockGetStoreRef(...args),
    getServices: (...args: unknown[]) => mockGetServices(...args)
  }
}))

const nuevoCliente = () =>
  new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } })

const nuevosLoaders = (): jest.Mocked<PortalLoaders> => ({
  booking: jest.fn().mockResolvedValue({}),
  clientAppointments: jest.fn().mockResolvedValue({})
})

beforeEach(() => {
  mockGetStore.mockReset().mockResolvedValue({ public_id: 'store-1', slug: 'sol', name: 'Sol' })
  mockGetStoreRef.mockReset().mockResolvedValue({
    store_public_id: 'store-1',
    name: 'Sol',
    accepts_new_bookings: true
  })
  mockGetServices.mockReset().mockResolvedValue([{ public_id: 'svc-1' }])
})

describe('prefetchPortal', () => {
  it('/b/:slug trae el chunk de la reserva, la tienda y despues sus servicios', async () => {
    const queryClient = nuevoCliente()
    const loaders = nuevosLoaders()

    await prefetchPortal('/b/sol', queryClient, loaders)

    expect(loaders.booking).toHaveBeenCalledTimes(1)
    expect(loaders.clientAppointments).not.toHaveBeenCalled()
    expect(mockGetStore).toHaveBeenCalledWith('sol')
    expect(mockGetServices).toHaveBeenCalledWith('store-1')
    expect(mockGetStoreRef).not.toHaveBeenCalled()
    // Mismas claves que usePublicStore y usePublicServices: con otra clave el
    // hook no encuentra el dato y la pagina repite la request.
    expect(queryClient.getQueryData(['public-store', 'sol'])).toEqual(
      expect.objectContaining({ public_id: 'store-1' })
    )
    expect(queryClient.getQueryData(['public-services', 'store-1'])).toEqual([
      { public_id: 'svc-1' }
    ])
  })

  it('la pagina que monta despues usa lo ya traido y no repite las requests', async () => {
    const queryClient = nuevoCliente()
    await prefetchPortal('/b/sol', queryClient, nuevosLoaders())
    await prefetchPortal('/b/sol/mis-turnos', queryClient, nuevosLoaders())
    const wrapper = ({ children }: { children: ReactNode }) =>
      createElement(QueryClientProvider, { client: queryClient }, children)

    const { result } = renderHook(
      () => ({
        store: usePublicStore('sol'),
        services: usePublicServices('store-1'),
        ref: usePublicStoreRef('sol')
      }),
      { wrapper }
    )

    // El primer render ya tiene los datos: nada quedo esperando a la red.
    expect(result.current.store.data).toEqual(expect.objectContaining({ public_id: 'store-1' }))
    expect(result.current.services.data).toEqual([{ public_id: 'svc-1' }])
    expect(result.current.ref.data).toEqual(expect.objectContaining({ name: 'Sol' }))
    // Y frescos: montar no dispara un refetch.
    await waitFor(() => expect(result.current.store.isFetching).toBe(false))
    expect(mockGetStore).toHaveBeenCalledTimes(1)
    expect(mockGetServices).toHaveBeenCalledTimes(1)
    expect(mockGetStoreRef).toHaveBeenCalledTimes(1)
  })

  it('/booking/:slug hace lo mismo que /b/:slug', async () => {
    const loaders = nuevosLoaders()

    await prefetchPortal('/booking/sol', nuevoCliente(), loaders)

    expect(loaders.booking).toHaveBeenCalledTimes(1)
    expect(mockGetStore).toHaveBeenCalledWith('sol')
    expect(mockGetServices).toHaveBeenCalledWith('store-1')
  })

  it('/booking/:slug/mis-turnos trae su chunk y el ref de la tienda, no la vitrina', async () => {
    const queryClient = nuevoCliente()
    const loaders = nuevosLoaders()

    await prefetchPortal('/booking/sol/mis-turnos', queryClient, loaders)

    expect(loaders.clientAppointments).toHaveBeenCalledTimes(1)
    expect(loaders.booking).not.toHaveBeenCalled()
    expect(mockGetStoreRef).toHaveBeenCalledWith('sol')
    expect(mockGetStore).not.toHaveBeenCalled()
    expect(queryClient.getQueryData(['public-store-ref', 'sol'])).toEqual(
      expect.objectContaining({ store_public_id: 'store-1' })
    )
  })

  it('una ruta del panel no pide nada', async () => {
    const loaders = nuevosLoaders()

    await prefetchPortal('/dashboard/calendar', nuevoCliente(), loaders)

    expect(loaders.booking).not.toHaveBeenCalled()
    expect(loaders.clientAppointments).not.toHaveBeenCalled()
    expect(mockGetStore).not.toHaveBeenCalled()
    expect(mockGetStoreRef).not.toHaveBeenCalled()
    expect(mockGetServices).not.toHaveBeenCalled()
  })

  it('decodifica el slug como lo hace useParams', async () => {
    const queryClient = nuevoCliente()

    await prefetchPortal('/b/mi%20tienda', queryClient, nuevosLoaders())

    expect(mockGetStore).toHaveBeenCalledWith('mi tienda')
    expect(queryClient.getQueryData(['public-store', 'mi tienda'])).toBeDefined()
  })

  it('una tienda inexistente (404) no rompe ni pide servicios', async () => {
    mockGetStore.mockRejectedValue(new NotFoundError('Negocio no encontrado'))
    const loaders = nuevosLoaders()

    await expect(prefetchPortal('/b/nada', nuevoCliente(), loaders)).resolves.toBeUndefined()

    expect(loaders.booking).toHaveBeenCalledTimes(1)
    expect(mockGetServices).not.toHaveBeenCalled()
  })

  it('un chunk que no carga tampoco rompe', async () => {
    const loaders = nuevosLoaders()
    loaders.booking.mockRejectedValue(new Error('Failed to fetch dynamically imported module'))

    await expect(prefetchPortal('/b/sol', nuevoCliente(), loaders)).resolves.toBeUndefined()

    expect(mockGetServices).toHaveBeenCalledWith('store-1')
  })

  it('cubre todas las rutas publicas con :slug de la tabla de rutas', async () => {
    // Si F12-06 suma o renombra una ruta del portal, este caso avisa que el
    // prefetch quedo atras.
    const rutas = PUBLIC_ROUTES.flatMap((ruta) => (ruta.path?.includes(':slug') ? [ruta.path] : []))
    expect(rutas.length).toBeGreaterThan(0)

    for (const ruta of rutas) {
      mockGetStore.mockClear()
      mockGetStoreRef.mockClear()
      await prefetchPortal(ruta.replace(':slug', 'sol'), nuevoCliente(), nuevosLoaders())
      const pedido = ruta.endsWith('/mis-turnos') ? mockGetStoreRef : mockGetStore
      expect(pedido).toHaveBeenCalledWith('sol')
    }
  })
})
