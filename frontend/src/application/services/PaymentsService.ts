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

export interface GatewayConfigUpsertPayload {
  provider: 'mercadopago' | 'stripe'
  access_token?: string
  public_key?: string
  webhook_secret?: string
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
}

export interface ReconciliationSummary {
  pending_payments: number
  approved_payments: number
  rejected_payments: number
  manual_confirmed_payments: number
  refunded_payments: number
  total_pending_amount: number
  total_approved_amount: number
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

export interface PromotionPayload {
  code: string
  title: string
  description?: string
  promotion_type: 'percent' | 'fixed'
  value: number
  min_service_amount?: number
  max_uses?: number
  valid_from?: string
  valid_until?: string
  is_active?: boolean
}

export class PaymentsService {
  async getGatewayConfig(): Promise<GatewayConfig> {
    const { data } = await apiClient.get<GatewayConfig>('/payments/gateway-config')
    return data
  }

  async upsertGatewayConfig(payload: GatewayConfigUpsertPayload): Promise<GatewayConfig> {
    const { data } = await apiClient.put<GatewayConfig>('/payments/gateway-config', payload)
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
    const { data } = await apiClient.get<PromotionRecord[]>('/promotions', {
      params: { include_inactive: includeInactive }
    })
    return data
  }

  async createPromotion(payload: PromotionPayload): Promise<PromotionRecord> {
    const { data } = await apiClient.post<PromotionRecord>('/promotions', payload)
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
