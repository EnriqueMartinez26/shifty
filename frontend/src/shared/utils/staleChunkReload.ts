/**
 * Recarga una sola vez cuando un chunk viejo no carga tras un deploy (F4-12).
 *
 * Cada pagina se carga con `lazy`: despues de un deploy, la pestana abierta
 * pide chunks con el hash anterior, nginx responde 404 (`try_files $uri
 * =404`) y la pestana quedaba en blanco. Vite avisa con `vite:preloadError`;
 * recargar trae el index.html nuevo con los hashes vigentes.
 *
 * La marca en sessionStorage evita el bucle: si ya se recargo hace menos de
 * 60 s, el error sigue su curso y lo muestra el error boundary. Si el storage
 * no existe o tira, un flag en memoria limita la recarga a una por vida de la
 * pagina. Vive en `shared/` (y no en `main.tsx`) para que la mida la cobertura.
 */

const RELOAD_MARK_KEY = 'shifty:chunk-reload'
const RELOAD_WINDOW_MS = 60_000

/** True si hay una marca de recarga de hace menos de la ventana. */
const hasRecentMark = (storage: Storage, current: number): boolean => {
  const raw = storage.getItem(RELOAD_MARK_KEY)
  if (raw === null) return false
  const mark = Number(raw)
  if (Number.isNaN(mark)) return false
  return current - mark < RELOAD_WINDOW_MS
}

/**
 * Escucha `vite:preloadError` en `win`. Devuelve la funcion que deja de
 * escuchar (la usan los tests; en la app se instala una vez y no se quita).
 */
export const installStaleChunkReload = (
  win: Window = window,
  reload: () => void = () => win.location.reload(),
  now: () => number = Date.now
): (() => void) => {
  let reloadedWithoutStorage = false

  const onPreloadError = (event: Event): void => {
    const current = now()
    try {
      const storage = win.sessionStorage
      if (hasRecentMark(storage, current)) return
      storage.setItem(RELOAD_MARK_KEY, String(current))
    } catch {
      // sin storage (privado, bloqueado): una recarga por vida de la pagina
      if (reloadedWithoutStorage) return
      reloadedWithoutStorage = true
    }
    event.preventDefault()
    reload()
  }

  win.addEventListener('vite:preloadError', onPreloadError)
  return () => win.removeEventListener('vite:preloadError', onPreloadError)
}
