import type { RemainderPaymentMethod } from '@domain/value-objects/AppointmentCharge'

import apiClient from '@infrastructure/http/client'

export interface GatewayConfig {
  provider: string
  configured: boolean
  public_key?: string | null
  access_token_masked?: string | null
  connection_mode?: string | null
  oauth_user_id?: string | null
  oauth_connected_at?: string | null
  oauth_supported: boolean
}

export interface MercadoPagoOAuthStart {
  auth_url: string
  qr_url: string
  expires_at: string
}

export interface PaymentPreference {
  payment_public_id: string
  appointment_id: string
  amount: number
  original_amount?: number | null
  discount_amount?: number | null
  currency: string
  preference_id?: string | null
  payment_link?: string | null
  promotion_code?: string | null
  status: string
}

export interface PaymentRecord {
  public_id: string
  appointment_id: string
  amount: number
  currency: string
  status: string
  paid_at?: string | null
  /**
   * Al registrar una devolucion: el resto vivo del turno, que la devolucion
   * no revierte (D-20261008-01); null si no hay.
   */
  live_remainder_amount?: string | null
}

export interface ReconciliationSummary {
  pending_payments: number
  approved_payments: number
  rejected_payments: number
  manual_confirmed_payments: number
  refunded_payments: number
  total_pending_amount: number
  total_approved_amount: number
  /** Restos vivos pagados aparte del cobro (D-20261008-01), aparte del total. */
  remainder_payments?: number
  total_remainder_amount?: number | string
  pending_webhooks: number
  failed_webhooks: number
  pending_outbox: number
}

export interface OutboxStats {
  pending: number
  pending_with_error: number
  processed: number
}

export interface AppointmentSearchItem {
  public_id: string
  starts_at: string
  ends_at: string
  status: string
  service_name: string
  service_id: string
  staff_name: string
  staff_id: string
  client_name: string
  client_id: string
  /** Precio congelado del turno (texto decimal); null en turnos historicos. */
  price_amount?: string | null
  /** Cobro del turno (a lo sumo uno): estado e importe, o null si no tiene. */
  payment_status?: string | null
  payment_amount?: string | null
  /** Saldo del turno que calcula el backend (D-20261008-01). */
  remaining_amount?: string | null
  /** Resto vivo registrado aparte del cobro, o null. */
  remainder_payment?: RemainderPaymentSummary | null
}

interface RemainderPaymentSummary {
  amount: string
  method?: string | null
  created_at: string
}

export interface RemainderPaymentRecord {
  public_id: string
  appointment_id: string
  amount: string
  method?: string | null
  created_at: string
  reverted_at?: string | null
  remaining_amount: string
}

export interface RemainderPaymentInput {
  amount: number
  method: RemainderPaymentMethod | null
  /** Una por dialogo: un reintento del mismo envio no registra dos restos. */
  idempotencyKey: string
}

export interface ProcessOutboxResult {
  processed: number
  failed: number
  inspected: number
}

export interface PromotionRecord {
  public_id: string
  code: string
  title: string
  description?: string | null
  promotion_type: 'percent' | 'fixed'
  value: number
  min_service_amount?: number | null
  max_uses?: number | null
  current_uses: number
  valid_from?: string | null
  valid_until?: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

// Los opcionales aceptan null: en el PATCH (exclude_unset) un null explicito
// borra el campo y un undefined no viaja. code, title, promotion_type y value
// nunca van en null: el backend los asigna con setattr y la columna no lo admite.
export interface PromotionPayload {
  code: string
  title: string
  description?: string | null
  promotion_type: 'percent' | 'fixed'
  value: number
  min_service_amount?: number | null
  max_uses?: number | null
  valid_from?: string | null
  valid_until?: string | null
  is_active?: boolean
}

class PaymentsService {
  async getGatewayConfig(): Promise<GatewayConfig> {
    const { data } = await apiClient.get<GatewayConfig>('/payments/gateway-config')
    return data
  }

  async startMercadoPagoOAuth(): Promise<MercadoPagoOAuthStart> {
    const { data } = await apiClient.post<MercadoPagoOAuthStart>(
      '/payments/mercadopago/oauth/start'
    )
    return data
  }

  async refreshMercadoPagoOAuth(): Promise<GatewayConfig> {
    const { data } = await apiClient.post<GatewayConfig>('/payments/mercadopago/oauth/refresh')
    return data
  }

  async disconnectMercadoPagoOAuth(): Promise<{ disconnected: boolean }> {
    const { data } = await apiClient.delete<{ disconnected: boolean }>(
      '/payments/mercadopago/oauth/connection'
    )
    return data
  }

  async getAppointments(): Promise<AppointmentSearchItem[]> {
    const { data } = await apiClient.get<{ results: AppointmentSearchItem[] }>(
      '/appointments/search',
      {
        params: { page: 1, page_size: 50 }
      }
    )
    return data.results
  }

  async createPreference(appointmentId: string): Promise<PaymentPreference> {
    const { data } = await apiClient.post<PaymentPreference>(
      `/payments/preferences/${appointmentId}`
    )
    return data
  }

  async listPromotions(includeInactive = true): Promise<PromotionRecord[]> {
    const { data } = await apiClient.get<PromotionRecord[]>('/promotions/', {
      params: { include_inactive: includeInactive }
    })
    return data
  }

  async createPromotion(payload: PromotionPayload): Promise<PromotionRecord> {
    const { data } = await apiClient.post<PromotionRecord>('/promotions/', payload)
    return data
  }

  async updatePromotion(
    promotionId: string,
    payload: Partial<PromotionPayload>
  ): Promise<PromotionRecord> {
    const { data } = await apiClient.patch<PromotionRecord>(`/promotions/${promotionId}`, payload)
    return data
  }

  async manualConfirm(
    appointmentId: string,
    amount?: number,
    notes?: string
  ): Promise<PaymentRecord> {
    const { data } = await apiClient.post<PaymentRecord>(
      `/payments/${appointmentId}/manual-confirm`,
      {
        amount,
        notes
      }
    )
    return data
  }

  /** Saldo restante por turno (D-20261008-01): el resto pagado aparte. */
  async recordRemainingPayment(
    appointmentId: string,
    { amount, method, idempotencyKey }: RemainderPaymentInput
  ): Promise<RemainderPaymentRecord> {
    const { data } = await apiClient.post<RemainderPaymentRecord>(
      `/payments/${appointmentId}/remaining-payment`,
      { amount, method, idempotency_key: idempotencyKey }
    )
    return data
  }

  /** Solo admin: marca revertido el resto (la devolucion se hizo por fuera). */
  async revertRemainingPayment(appointmentId: string): Promise<RemainderPaymentRecord> {
    const { data } = await apiClient.post<RemainderPaymentRecord>(
      `/payments/${appointmentId}/remaining-payment/revert`
    )
    return data
  }

  async refund(
    paymentId: string,
    amount?: number,
    reason?: string,
    manual?: boolean
  ): Promise<PaymentRecord> {
    const { data } = await apiClient.post<PaymentRecord>(`/payments/${paymentId}/refund`, {
      amount,
      reason,
      manual
    })
    return data
  }

  async getReconciliationSummary(): Promise<ReconciliationSummary> {
    const { data } = await apiClient.get<ReconciliationSummary>('/payments/reconciliation/summary')
    return data
  }

  async getOutboxStats(): Promise<OutboxStats> {
    const { data } = await apiClient.get<OutboxStats>('/payments/outbox/stats')
    return data
  }

  async processOutbox(limit?: number): Promise<ProcessOutboxResult> {
    const { data } = await apiClient.post<ProcessOutboxResult>('/payments/outbox/process', null, {
      params: { limit: limit ?? 100 }
    })
    return data
  }
}

export const paymentsService = new PaymentsService()
