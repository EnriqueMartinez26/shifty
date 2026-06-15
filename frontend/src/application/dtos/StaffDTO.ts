export interface StaffResponseDTO {
  public_id: string
  first_name: string
  last_name: string
  email: string
  display_name: string | null
  is_active: boolean
  service_ids: string[]
}

export interface CreateStaffRequestDTO {
  first_name: string
  last_name: string
  email: string
  display_name: string
  service_ids: string[]
}
