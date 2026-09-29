export interface StaffResponseDTO {
  public_id: string
  kind?: 'person' | 'resource'
  first_name: string
  last_name: string
  email: string | null
  display_name: string | null
  is_active: boolean
  service_ids: string[]
  /** Franjas propias (`HH:MM:SS`, 0 = lunes). Solo lectura; no viaja al escribir. */
  schedules?: StaffScheduleDTO[]
}

interface StaffScheduleDTO {
  public_id?: string
  day_of_week: number
  start_time: string
  end_time: string
}
