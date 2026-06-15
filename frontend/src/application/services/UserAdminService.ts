import apiClient from '@infrastructure/http/client'

export type UserRole = 'admin' | 'staff' | 'receptionist' | 'client'

export interface ManagedUser {
  public_id: string
  email: string
  first_name: string | null
  last_name: string | null
  phone: string | null
  role: UserRole
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface CreateUserPayload {
  email: string
  password: string
  first_name?: string
  last_name?: string
  phone?: string
  role: UserRole
}

export interface UpdateUserPayload {
  first_name?: string
  last_name?: string
  phone?: string
  role?: UserRole
  password?: string
  is_active?: boolean
}

export class UserAdminService {
  async list(includeInactive = false): Promise<ManagedUser[]> {
    const { data } = await apiClient.get<ManagedUser[]>(
      `/users/?include_inactive=${includeInactive}`
    )
    return data
  }

  async create(payload: CreateUserPayload): Promise<ManagedUser> {
    const { data } = await apiClient.post<ManagedUser>('/users/', payload)
    return data
  }

  async update(publicId: string, payload: UpdateUserPayload): Promise<ManagedUser> {
    const { data } = await apiClient.patch<ManagedUser>(`/users/${publicId}`, payload)
    return data
  }

  async delete(publicId: string): Promise<void> {
    await apiClient.delete(`/users/${publicId}`)
  }
}

export const userAdminService = new UserAdminService()
