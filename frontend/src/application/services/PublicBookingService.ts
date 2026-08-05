import apiClient from '@infrastructure/http/client'

import type { BusinessType } from '@shared/types/business'

import type { StoreCustomField } from './StoreSettingsService'

export interface PublicStoreFeatureFlags {
  payments: boolean
  ledger: boolean
  advanced_reports: boolean
  new_calendar: boolean
  otp_booking: boolean
}

export interface PublicStore {
  public_id: string
  name: string
  slug: string
  business_type: BusinessType
  logo_url: string | null
  primary_color: string
  cancellation_hours: number
  description?: string | null
  cover_url?: string | null
  whatsapp_number?: string | null
  website_url?: string | null
  allow_manual_coordination?: boolean
  deposit_policy?: string | null
  custom_client_fields: StoreCustomField[]
  feature_flags: PublicStoreFeatureFlags
}

export interface PublicService {
  public_id: string
  name: string
  description: string | null
  duration_minutes: number
  price: number
  deposit_mode: 'none' | 'optional' | 'required'
  deposit_type: 'percent' | 'fixed' | 'full'
  deposit_amount: number | null
  color: string | null
  image_url: string | null
}

export interface PublicStaff {
  public_id: string
  first_name: string
  last_name: string
  display_name: string
  service_ids: string[]
}

export interface AvailabilitySlot {
  staff_id: string
  staff_name: string
  starts_at: string
  ends_at: string
  status: 'available' | 'booked' | 'blocked'
  start_time?: string
  end_time?: string
  reason?: string | null
}

export interface PublicBookingPayload {
  store_public_id: string
  service_id: string
  staff_id?: string
  starts_at: string
  notes?: string
  idempotency_key: string
  client_name: string
  client_email?: string
  client_phone: string
  custom_fields?: Record<string, string>
  promotion_code?: string
  payment_method?: 'manual' | 'mercadopago'
  accepts_terms?: boolean
}

export interface BookingConfirmation {
  public_id: string
  service_id: string
  service_name: string
  staff_id: string
  staff_name: string
  starts_at: string
  ends_at: string
  status: string
  client_name: string
  client_phone: string
  notes?: string | null
  custom_fields?: Record<string, string>
  payment_required: boolean
  payment_status?: string | null
  payment_link?: string | null
  payment_public_id?: string | null
  payment_amount?: number | null
  promotion_code?: string | null
  service_price?: number | null
  discount_amount?: number | null
  final_price?: number | null
}

export interface PromotionPreview {
  code: string
  title: string
  promotion_type: 'percent' | 'fixed'
  base_amount: number
  discount_amount: number
  final_amount: number
}

export interface PublicPaymentStatus {
  payment_public_id: string
  appointment_public_id: string
  payment_status: string
  appointment_status: string
  amount: number
  currency: string
  starts_at: string
}

export interface OtpRequestPayload {
  store_public_id: string
  phone: string
  channel: 'whatsapp' | 'sms'
}

export interface OtpRequestResponse {
  ok: boolean
  expires_at: string
  debug_code?: string
}

export interface OtpVerifyPayload {
  store_public_id: string
  phone: string
  code: string
}

export interface OtpVerifyResponse {
  ok: boolean
  verified_at: string
  phone: string
}

export class PublicBookingService {
  async getStore(slug: string): Promise<PublicStore> {
    const { data } = await apiClient.get<PublicStore>(`/public/stores/${slug}`)
    return data
  }

  async getServices(storePublicId: string): Promise<PublicService[]> {
    const { data } = await apiClient.get<PublicService[]>('/public/services', {
      params: { store_public_id: storePublicId }
    })
    return data
  }

  async getStaff(storePublicId: string, serviceId?: string): Promise<PublicStaff[]> {
    const { data } = await apiClient.get<PublicStaff[]>('/public/staff', {
      params: { store_public_id: storePublicId, service_id: serviceId }
    })
    return data
  }

  async getAvailability(
    storePublicId: string,
    serviceId: string,
    date: string,
    forceAll = false
  ): Promise<AvailabilitySlot[]> {
    const { data } = await apiClient.get<AvailabilitySlot[]>('/public/availability', {
      params: { store_public_id: storePublicId, service_id: serviceId, date, force_all: forceAll }
    })
    return data
  }

  async createBooking(payload: PublicBookingPayload): Promise<BookingConfirmation> {
    const { data } = await apiClient.post<BookingConfirmation>('/public/appointments', payload)
    return data
  }

  async getPaymentStatus(
    storePublicId: string,
    paymentPublicId: string
  ): Promise<PublicPaymentStatus> {
    const { data } = await apiClient.get<PublicPaymentStatus>(
      `/public/payments/${paymentPublicId}/status`,
      { params: { store_public_id: storePublicId } }
    )
    return data
  }

  async previewPromotion(
    storePublicId: string,
    serviceId: string,
    code: string
  ): Promise<PromotionPreview> {
    const { data } = await apiClient.get<PromotionPreview>('/public/promotions/preview', {
      params: { store_public_id: storePublicId, service_id: serviceId, code }
    })
    return data
  }

  async requestOtp(payload: OtpRequestPayload): Promise<OtpRequestResponse> {
    const { data } = await apiClient.post<OtpRequestResponse>('/public/otp/request', payload)
    return data
  }

  async verifyOtp(payload: OtpVerifyPayload): Promise<OtpVerifyResponse> {
    const { data } = await apiClient.post<OtpVerifyResponse>('/public/otp/verify', payload)
    return data
  }
}

export const publicBookingService = new PublicBookingService()
