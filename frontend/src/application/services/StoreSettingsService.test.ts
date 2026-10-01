// F9-08 (2026-09-30): cobertura de la configuracion de la tienda. Path literal
// (regla 23), verbo y cuerpo por metodo; el logo viaja como multipart.
const mockGet = jest.fn()
const mockPatch = jest.fn()
const mockPut = jest.fn()
const mockPost = jest.fn()

jest.mock('@infrastructure/http/client', () => ({
  __esModule: true,
  default: {
    get: (...args: unknown[]) => mockGet(...args),
    patch: (...args: unknown[]) => mockPatch(...args),
    put: (...args: unknown[]) => mockPut(...args),
    post: (...args: unknown[]) => mockPost(...args)
  }
}))

import { storeSettingsService } from './StoreSettingsService'

describe('StoreSettingsService', () => {
  beforeEach(() => {
    for (const mock of [mockGet, mockPatch, mockPut, mockPost]) {
      mock.mockReset()
      mock.mockResolvedValue({ data: {} })
    }
  })

  it('getSubscription pide la suscripcion de la tienda por GET', async () => {
    await storeSettingsService.getSubscription()

    expect(mockGet).toHaveBeenCalledWith('/stores/me/subscription')
  })

  it('getSettings pide la tienda por GET', async () => {
    await storeSettingsService.getSettings()

    expect(mockGet).toHaveBeenCalledWith('/stores/me')
  })

  it('updateSettings manda solo los campos cambiados por PATCH', async () => {
    await storeSettingsService.updateSettings({ name: 'Barberia', buffer_minutes: 10 })

    expect(mockPatch).toHaveBeenCalledWith('/stores/me', { name: 'Barberia', buffer_minutes: 10 })
  })

  it('getFeatureFlags pide los flags por GET', async () => {
    await storeSettingsService.getFeatureFlags()

    expect(mockGet).toHaveBeenCalledWith('/stores/me/feature-flags')
  })

  it('updateFeatureFlags manda los flags por PUT', async () => {
    await storeSettingsService.updateFeatureFlags({ ledger: true })

    expect(mockPut).toHaveBeenCalledWith('/stores/me/feature-flags', { ledger: true })
  })

  it('uploadLogo manda un FormData multipart con kind=logo y el archivo', async () => {
    const file = new File(['png'], 'logo.png', { type: 'image/png' })

    await storeSettingsService.uploadLogo(file)

    const [path, body, config] = mockPost.mock.calls[0] as [string, FormData, unknown]
    expect(path).toBe('/stores/me/media')
    expect(body).toBeInstanceOf(FormData)
    expect(body.get('kind')).toBe('logo')
    expect(body.get('file')).toBe(file)
    expect(config).toEqual({ headers: { 'Content-Type': 'multipart/form-data' } })
  })
})
