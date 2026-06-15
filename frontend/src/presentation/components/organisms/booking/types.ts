export interface BookingClientData {
  name: string
  email: string
  phone: string
  notes: string
  customFields: Record<string, string>
}

export interface BookingWizardState {
  serviceId: string | null
  requestedStaffId: string | null
  assignedStaffId: string | null
  date: string | null
  startTime: string | null
  client: BookingClientData
  promotionCode: string
  idempotencyKey: string
}
