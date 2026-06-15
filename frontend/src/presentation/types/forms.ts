export interface ServiceFormValues {
  name: string
  description: string
  durationMinutes: number
  price: number
  color: string
  imageUrl: string
  youtubeTrailerUrl: string
}

export interface StaffFormValues {
  first_name: string
  last_name: string
  email: string
  display_name: string
  service_ids: string[]
}

export interface UserFormValues {
  email: string
  password: string
  first_name: string
  last_name: string
  phone: string
  role: 'admin' | 'staff' | 'receptionist' | 'client'
}
