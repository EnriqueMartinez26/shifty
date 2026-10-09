import type { UserListQuery } from '@domain/repositories/IUserRepository'

/**
 * Largo de pagina del listado de usuarios. El backend corta en `limit` y la
 * tabla crece con cada cliente de la reserva publica: el resto llega por
 * paginas con `offset` ("Ver mas", F4-03), no filtrando en memoria.
 */
const USER_LIST_LIMIT = 100

/**
 * Traduce lo tipeado a la busqueda del servidor. El backend no busca `q` en el
 * email, asi que un termino con `@` va como `email` exacto (en minusculas,
 * como se guarda). `q` exige 2 caracteres: menos que eso lista sin filtro.
 */
export const toUserListQuery = (term: string): UserListQuery => {
  const trimmed = term.trim()
  const base: UserListQuery = { limit: USER_LIST_LIMIT, includeInactive: true }
  if (trimmed.includes('@')) return { ...base, email: trimmed.toLowerCase() }
  if (trimmed.length >= 2) return { ...base, q: trimmed }
  return base
}
