export interface StaffResponseDTO {
  public_id: string
  kind?: 'person' | 'resource'
  first_name: string
  last_name: string
  email: string | null
  display_name: string | null
  is_active: boolean
  service_ids: string[]
}

export interface CreateStaffRequestDTO {
  kind?: 'person' | 'resource'
  first_name: string
  last_name: string
  email: string | null
  display_name: string
  service_ids: string[]
}
