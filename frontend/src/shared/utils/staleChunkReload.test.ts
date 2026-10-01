import { installStaleChunkReload } from './staleChunkReload'

/**
 * 2026-09-30: tras un deploy el chunk viejo da 404 y la pestaña queda en
 * blanco. Vite avisa con `vite:preloadError`; se recarga una sola vez para
 * traer el index.html nuevo, y un segundo fallo reciente llega al error
 * boundary en vez de entrar en un bucle de recargas.
 */

const MARK_KEY = 'shifty:chunk-reload'
const T0 = 1_790_000_000_000

const dispatchPreloadError = (): Event => {
  const event = new Event('vite:preloadError', { cancelable: true })
  window.dispatchEvent(event)
  return event
}

describe('installStaleChunkReload', () => {
  let uninstall: (() => void) | undefined

  beforeEach(() => {
    window.sessionStorage.clear()
  })

  afterEach(() => {
    uninstall?.()
    uninstall = undefined
    jest.restoreAllMocks()
  })

  it('el primer fallo de chunk recarga y cancela el error', () => {
    const reload = jest.fn()
    uninstall = installStaleChunkReload(window, reload, () => T0)

    const event = dispatchPreloadError()

    expect(reload).toHaveBeenCalledTimes(1)
    expect(event.defaultPrevented).toBe(true)
    expect(window.sessionStorage.getItem(MARK_KEY)).toBe(String(T0))
  })

  it('un segundo fallo dentro de 60 s no recarga y deja pasar el error', () => {
    const reload = jest.fn()
    let now = T0
    uninstall = installStaleChunkReload(window, reload, () => now)

    dispatchPreloadError()
    now = T0 + 59_000
    const second = dispatchPreloadError()

    expect(reload).toHaveBeenCalledTimes(1)
    expect(second.defaultPrevented).toBe(false)
  })

  it('con una marca de hace mas de 60 s vuelve a recargar', () => {
    window.sessionStorage.setItem(MARK_KEY, String(T0 - 60_001))
    const reload = jest.fn()
    uninstall = installStaleChunkReload(window, reload, () => T0)

    const event = dispatchPreloadError()

    expect(reload).toHaveBeenCalledTimes(1)
    expect(event.defaultPrevented).toBe(true)
    expect(window.sessionStorage.getItem(MARK_KEY)).toBe(String(T0))
  })

  it('una marca ilegible cuenta como sin marca y recarga', () => {
    window.sessionStorage.setItem(MARK_KEY, 'no es un numero')
    const reload = jest.fn()
    uninstall = installStaleChunkReload(window, reload, () => T0)

    const event = dispatchPreloadError()

    expect(reload).toHaveBeenCalledTimes(1)
    expect(event.defaultPrevented).toBe(true)
    expect(window.sessionStorage.getItem(MARK_KEY)).toBe(String(T0))
  })

  // Sin storage nada sobrevive a la recarga: si el deploy nuevo tambien esta
  // roto, recargar "una vez por vida de la pagina" se repetiria para siempre.
  it('sin storage no recarga ni cancela el error, para no entrar en bucle', () => {
    jest.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('storage bloqueado')
    })
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('storage bloqueado')
    })
    const reload = jest.fn()
    uninstall = installStaleChunkReload(window, reload, () => T0)

    const first = dispatchPreloadError()
    const second = dispatchPreloadError()

    expect(reload).not.toHaveBeenCalled()
    expect(first.defaultPrevented).toBe(false)
    expect(second.defaultPrevented).toBe(false)
  })

  it('si la marca no se puede guardar tampoco recarga', () => {
    jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('cuota llena')
    })
    const reload = jest.fn()
    uninstall = installStaleChunkReload(window, reload, () => T0)

    const event = dispatchPreloadError()

    expect(reload).not.toHaveBeenCalled()
    expect(event.defaultPrevented).toBe(false)
  })
})
