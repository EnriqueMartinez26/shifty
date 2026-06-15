export interface UserResponseDTO {
  public_id: string
  email: string
  first_name: string | null
  last_name: string | null
  phone: string | null
  role: 'admin' | 'staff' | 'receptionist' | 'client'
  is_active: boolean
  is_global_admin?: boolean
  created_at: string
  updated_at: string
}

export interface CreateUserRequestDTO {
  email: string
  password: string
  first_name?: string
  last_name?: string
  phone?: string
  role: 'admin' | 'staff' | 'receptionist' | 'client'
}
