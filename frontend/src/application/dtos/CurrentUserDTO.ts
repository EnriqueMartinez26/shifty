/** Respuesta de `GET /me` (`CurrentUserResponse` en docs/API_CONTRACT.md). */
export interface CurrentUserDTO {
  email: string
  role: string
  store_id: string | null
  public_id: string
  is_global_admin: boolean
  first_name: string | null
  last_name: string | null
}
