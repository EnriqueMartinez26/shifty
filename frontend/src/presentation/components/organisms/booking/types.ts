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
  /** Instante ISO (UTC) del slot elegido: es lo que se manda al reservar. */
  startsAt: string | null
  client: BookingClientData
  promotionCode: string
  idempotencyKey: string
}

export interface BookingOtpState {
  code: string
  /** El codigo va por email (SMTP existente); no hay WhatsApp ni SMS. */
  channel: 'email'
  /** Email al que se manda el codigo; arranca con el del formulario. */
  email: string
  verified: boolean
  verifiedPhone: string
  expiresAt: string
  error: string
  /**
   * El backend respondio OTP_RATE_LIMITED: no se ofrece pedir otro codigo
   * hasta recargar. Sin cuenta regresiva: la ventana del backend es
   * deslizante y cualquier numero seria una promesa falsa (F4-11).
   */
  rateLimited: boolean
}
