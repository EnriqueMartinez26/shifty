import React from 'react'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { act, renderHook, waitFor } from '@testing-library/react'

import {
  useStoreSettings,
  useUpdateStoreSettings,
  useUploadStoreCover,
  useUploadStoreLogo
} from './useStores'

// 2026-10-02 (F4-15): la configuracion de la tienda no tenia staleTime propio
// y con el global de 30 s se volvia a pedir en casi cada navegacion del panel,
// aunque solo cambia cuando el admin guarda.

const mockGetSettings = jest.fn()
const mockUpdateSettings = jest.fn()
const mockUploadLogo = jest.fn()
const mockUploadCover = jest.fn()

jest.mock('@application/services/StoreSettingsService', () => ({
  storeSettingsService: {
    getSettings: (...args: unknown[]) => mockGetSettings(...args),
    updateSettings: (...args: unknown[]) => mockUpdateSettings(...args),
    uploadLogo: (...args: unknown[]) => mockUploadLogo(...args),
    uploadCover: (...args: unknown[]) => mockUploadCover(...args)
  }
}))

// Sin staleTime global: lo que se prueba es el del hook.
const nuevoCliente = () =>
  new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })

const envoltorio = (queryClient: QueryClient) => {
  const Envoltorio = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  )
  return Envoltorio
}

describe('useStoreSettings', () => {
  beforeEach(() => {
    mockGetSettings.mockReset().mockResolvedValue({ name: 'Sol' })
    mockUpdateSettings.mockReset().mockResolvedValue({ name: 'Sol 2' })
  })

  it('volver a la pantalla dentro de los 5 minutos no la vuelve a pedir', async () => {
    const queryClient = nuevoCliente()
    const primera = renderHook(() => useStoreSettings(), { wrapper: envoltorio(queryClient) })
    await waitFor(() => expect(primera.result.current.isSuccess).toBe(true))
    primera.unmount()

    const segunda = renderHook(() => useStoreSettings(), { wrapper: envoltorio(queryClient) })

    expect(segunda.result.current.data).toEqual({ name: 'Sol' })
    expect(segunda.result.current.isStale).toBe(false)
    expect(mockGetSettings).toHaveBeenCalledTimes(1)
  })

  it('guardar la configuracion la vuelve a pedir aunque siga fresca', async () => {
    const queryClient = nuevoCliente()
    const { result } = renderHook(
      () => ({ settings: useStoreSettings(), update: useUpdateStoreSettings() }),
      { wrapper: envoltorio(queryClient) }
    )
    await waitFor(() => expect(result.current.settings.isSuccess).toBe(true))

    await act(async () => {
      await result.current.update.mutateAsync({ name: 'Sol 2' })
    })

    await waitFor(() => expect(mockGetSettings).toHaveBeenCalledTimes(2))
  })
})

// 2026-10-21 (S2): la portada se sube como el logo y refresca la configuracion
// igual, para que la vista previa muestre la imagen guardada.
describe('subir imagenes de la tienda', () => {
  beforeEach(() => {
    mockGetSettings.mockReset().mockResolvedValue({ name: 'Sol' })
    mockUploadLogo.mockReset().mockResolvedValue({ url: '/media/logo.png' })
    mockUploadCover.mockReset().mockResolvedValue({ url: '/media/cover.webp' })
  })

  it.each([
    ['el logo', useUploadStoreLogo, mockUploadLogo, mockUploadCover, '/media/logo.png'],
    ['la portada', useUploadStoreCover, mockUploadCover, mockUploadLogo, '/media/cover.webp']
  ])('subir %s llama a su servicio y vuelve a pedir la configuracion', async (...caso) => {
    const [, useUpload, servicio, otroServicio, url] = caso
    const queryClient = nuevoCliente()
    const archivo = new File(['x'], 'imagen.png', { type: 'image/png' })
    const { result } = renderHook(() => ({ settings: useStoreSettings(), upload: useUpload() }), {
      wrapper: envoltorio(queryClient)
    })
    await waitFor(() => expect(result.current.settings.isSuccess).toBe(true))

    let respuesta: unknown
    await act(async () => {
      respuesta = await result.current.upload.mutateAsync(archivo)
    })

    expect(respuesta).toEqual({ url })
    expect(servicio).toHaveBeenCalledWith(archivo)
    expect(otroServicio).not.toHaveBeenCalled()
    await waitFor(() => expect(mockGetSettings).toHaveBeenCalledTimes(2))
  })
})
