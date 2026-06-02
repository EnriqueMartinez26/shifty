export type AppointmentStatus = 'PENDING' | 'CONFIRMED' | 'COMPLETED' | 'CANCELLED' | 'ABSENT' | 'UNAVAILABLE';

export interface TimeSlot {
  staff_id: string;
  staff_name: string;
  starts_at: string; // ISO UTC
  ends_at: string;   // ISO UTC
  status: 'available' | 'booked' | 'blocked';
  reason?: string;
}

export interface Service {
  public_id: string;
  name: string;
  description?: string;
  duration_minutes: number;
  price: string;
  color?: string;
}

export interface Store {
  public_id: string;
  name: string;
  slug: string;
  logo_url?: string;
  primary_color: string;
  cancellation_hours: number;
}

export interface BookingData {
  store_public_id: string;
  service_id: string;
  staff_id: string;
  starts_at: string; // ISO UTC
  client_name: string;
  client_phone: string;
  client_email?: string;
  notes?: string;
  idempotency_key: string;
}
