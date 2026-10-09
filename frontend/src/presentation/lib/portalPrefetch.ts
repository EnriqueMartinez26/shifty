import type { QueryClient } from '@tanstack/react-query'

import { publicServicesQuery, publicStoreQuery, publicStoreRefQuery } from '../hooks/usePublic'

/**
 * Prefetch del portal publico segun la URL de entrada (F4-14). Sin esto, al
 * abrir /b/:slug la app montaba, recien ahi pedia el chunk de la pagina y,
 * cuando el chunk cargaba, la tienda y despues sus servicios: tres viajes en
 * serie. Aca salen en paralelo antes de montar.
 *
 * Las queries salen de las mismas fabricas que los hooks de `usePublic`: la
 * pagina encuentra el dato (o la request en vuelo) bajo la misma clave y no
 * la repite. Nunca rechaza: es solo un adelanto y la pagina vuelve a pedir lo
 * que falte.
 */

/** Los `import()` de las paginas, inyectados para poder testear sin Vite. */
export interface PortalLoaders {
  booking: () => Promise<unknown>
  clientAppointments: () => Promise<unknown>
}

// Mismas rutas que PUBLIC_ROUTES (routes/appRoutes.ts); el test recorre esa
// tabla y falla si una ruta del portal con :slug queda sin prefetch. Como
// react-router, sin distinguir mayusculas y tolerando la barra final.
const CLIENT_APPOINTMENTS_PATH = /^\/(?:b|booking)\/([^/]+)\/mis-turnos\/*$/i
const BOOKING_PATH = /^\/(?:b|booking)\/([^/]+)\/*$/i

// Igual que `decodePath` de react-router, de donde sale el `slug` de
// useParams: decodifica el segmento, deja una "/" codificada como %2F y ante
// un escape roto usa el texto crudo.
const decodeSlug = (segment: string): string => {
  try {
    return decodeURIComponent(segment).replace(/\//g, '%2F')
  } catch {
    return segment
  }
}

const slugOf = (pattern: RegExp, pathname: string): string | undefined => {
  const segment = pattern.exec(pathname)?.[1]
  return segment === undefined ? undefined : decodeSlug(segment)
}

const ignore = () => undefined

export const prefetchPortal = async (
  pathname: string,
  queryClient: QueryClient,
  loaders: PortalLoaders
): Promise<void> => {
  const appointmentsSlug = slugOf(CLIENT_APPOINTMENTS_PATH, pathname)
  if (appointmentsSlug !== undefined) {
    await Promise.all([
      loaders.clientAppointments().catch(ignore),
      queryClient.prefetchQuery(publicStoreRefQuery(appointmentsSlug))
    ])
    return
  }

  const bookingSlug = slugOf(BOOKING_PATH, pathname)
  if (bookingSlug === undefined) return
  await Promise.all([
    loaders.booking().catch(ignore),
    queryClient
      .fetchQuery(publicStoreQuery(bookingSlug))
      .then((store) => queryClient.prefetchQuery(publicServicesQuery(store.public_id)), ignore)
  ])
}
