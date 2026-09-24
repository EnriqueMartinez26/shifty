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
