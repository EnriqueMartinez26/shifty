export interface AppointmentResponseDTO {
  public_id: string;
  service_id: string;
  service_name: string;
  staff_id: string;
  client_name: string;
  starts_at: string;
  ends_at: string;
  status: string;
  notes: string | null;
}

export interface CreateBookingRequestDTO {
  store_public_id?: string;
  service_id: string;
  staff_id: string;
  starts_at: string;
  client_name: string;
  client_email: string;
  client_phone: string;
  notes?: string;
  idempotency_key?: string;
}
