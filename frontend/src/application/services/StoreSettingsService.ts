import apiClient from '@infrastructure/http/client'

import type { BusinessType } from '@shared/types/business'

interface BusinessHourPeriod {
  open: string
  close: string
}

type StoreCustomFieldType = 'text' | 'textarea' | 'tel' | 'email' | 'date' | 'select'

export interface StoreCustomFieldOption {
  label: string
  value: string
}

export interface StoreCustomField {
  key: string
  label: string
  type: StoreCustomFieldType
  required: boolean
  placeholder?: string | null
  help_text?: string | null
  options: StoreCustomFieldOption[]
}

export interface StoreFeatureFlags {
  payments: boolean
  ledger: boolean
  advanced_reports: boolean
  new_calendar: boolean
  otp_booking: boolean
  /** Varios servicios en un turno, con el mismo profesional (apagado por defecto). */
  multi_service_booking: boolean
}

/**
 * Que parte de la portada se ve cuando se recorta (S10.1). `null`: sin
 * elegir. Opcional en las respuestas: un backend anterior no lo manda.
 */
export type CoverPosition = 'top' | 'center' | 'bottom'

export interface StoreSettings {
  public_id: string
  name: string
  slug: string
  business_type: BusinessType
  logo_url: string | null
  primary_color: string
  cover_url?: string | null
  cover_position?: CoverPosition | null
  description?: string | null
  whatsapp_number?: string | null
  instagram_url?: string | null
  facebook_url?: string | null
  website_url?: string | null
  custom_client_fields: StoreCustomField[]
  cancellation_hours: number
  min_booking_notice_hours: number
  buffer_minutes: number
  allow_manual_coordination: boolean
  deposit_policy?: string | null
  /** Recargos de seña en puntos porcentuales del precio; 0 apaga la regla. */
  deposit_far_notice_days: number
  deposit_far_notice_extra_percent: number
  deposit_new_client_extra_percent: number
  deposit_absent_client_extra_percent: number
  business_hours: Record<string, BusinessHourPeriod[]>
  send_email_confirmation: boolean
  send_email_reminders: boolean
  feature_flags?: StoreFeatureFlags
}

export interface StoreSubscriptionStatus {
  status: 'none' | 'active' | 'past_due' | 'suspended' | 'cancelled'
  plan_name: string | null
  current_period_end: string | null
  days_left: number | null
  grace_until: string | null
  warn: boolean
  /** Suspendida: el panel es de solo lectura y la pagina publica no se ve. */
  blocks_writes: boolean
}

export interface StoreUpdatePayload {
  name?: string
  slug?: string
  business_type?: BusinessType
  logo_url?: string | null
  primary_color?: string
  cover_url?: string | null
  cover_position?: CoverPosition | null
  description?: string | null
  whatsapp_number?: string | null
  instagram_url?: string | null
  facebook_url?: string | null
  website_url?: string | null
  custom_client_fields?: StoreCustomField[]
  cancellation_hours?: number
  min_booking_notice_hours?: number
  buffer_minutes?: number
  allow_manual_coordination?: boolean
  deposit_policy?: string | null
  deposit_far_notice_days?: number
  deposit_far_notice_extra_percent?: number
  deposit_new_client_extra_percent?: number
  deposit_absent_client_extra_percent?: number
  business_hours?: Record<string, BusinessHourPeriod[]>
  send_email_confirmation?: boolean
  send_email_reminders?: boolean
}

export interface StoreMediaUploadResult {
  url: string
  media_id: string
  kind: string
}

export interface StoreFeatureFlagsResponse {
  flags: StoreFeatureFlags
}

class StoreSettingsService {
  async getSubscription(): Promise<StoreSubscriptionStatus> {
    const { data } = await apiClient.get<StoreSubscriptionStatus>('/stores/me/subscription')
    return data
  }

  async getSettings(): Promise<StoreSettings> {
    const { data } = await apiClient.get<StoreSettings>('/stores/me')
    return data
  }

  async updateSettings(payload: StoreUpdatePayload): Promise<StoreSettings> {
    const { data } = await apiClient.patch<StoreSettings>('/stores/me', payload)
    return data
  }

  async getFeatureFlags(): Promise<StoreFeatureFlagsResponse> {
    const { data } = await apiClient.get<StoreFeatureFlagsResponse>('/stores/me/feature-flags')
    return data
  }

  async updateFeatureFlags(
    payload: Partial<StoreFeatureFlags>
  ): Promise<StoreFeatureFlagsResponse> {
    const { data } = await apiClient.put<StoreFeatureFlagsResponse>(
      '/stores/me/feature-flags',
      payload
    )
    return data
  }

  uploadLogo(file: File): Promise<StoreMediaUploadResult> {
    return this.uploadImage('logo', file)
  }

  uploadCover(file: File): Promise<StoreMediaUploadResult> {
    return this.uploadImage('cover', file)
  }

  /** `kind` es `ALLOWED_KINDS` de backend/modules/stores/media.py. */
  private async uploadImage(kind: 'logo' | 'cover', file: File): Promise<StoreMediaUploadResult> {
    const form = new FormData()
    form.append('kind', kind)
    form.append('file', file)
    // Se fuerza multipart (el cliente por defecto manda application/json) para
    // que axios/el navegador arme el boundary; el backend valida por magic bytes.
    const { data } = await apiClient.post<StoreMediaUploadResult>('/stores/me/media', form, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    return data
  }
}

export const storeSettingsService = new StoreSettingsService()
