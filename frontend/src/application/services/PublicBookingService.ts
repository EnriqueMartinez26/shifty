import apiClient from '@infrastructure/http/client'

import type { BusinessType } from '@shared/types/business'

import { clientTokenConfig, forgetClientToken, rememberClientToken } from './clientToken'
import type { StoreCustomField } from './StoreSettingsService'

interface PublicStoreFeatureFlags {
  payments: boolean
  ledger: boolean
  advanced_reports: boolean
  new_calendar: boolean
  otp_booking: boolean
  /**
   * Varios servicios en un turno, con el mismo profesional. Opcional: una
   * respuesta sin la clave (backend anterior) es apagado.
   */
  multi_service_booking?: boolean
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

/**
 * Slug -> tienda para "Mis turnos" (FF-16). Responde tambien con la tienda
 * suspendida, cuando la vitrina da 404: cancelar y reprogramar siguen.
 */
export interface PublicStoreRef {
  store_public_id: string
  name: string
  accepts_new_bookings: boolean
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
  /** Adicionales del servicio, ordenados por `position`. */
  addons?: PublicServiceAddon[]
}

/** Un adicional suma precio por unidad, nunca tiempo. */
interface PublicServiceAddon {
  id: string
  name: string
  unit_price: number
  max_quantity: number
  position: number
}

/** Un adicional elegido, en el cuerpo de la reserva. */
export interface PublicBookingAddon {
  addon_id: string
  quantity: number
}

/** Un servicio sumado al principal en el mismo turno. */
interface BookedExtraService {
  public_id: string
  name: string
  duration_minutes: number
}

/**
 * Query repetida sin corchetes (`extra_service_id=a&extra_service_id=b`): el
 * formato por defecto de axios mandaria `extra_service_id[]=` y FastAPI no lo
 * reconoce. Vacio no viaja.
 */
const extraServiceParam = (ids: readonly string[] | undefined): string[] | undefined =>
  ids?.length ? [...ids] : undefined

/** Un adicional ya cobrado en el turno (precio congelado al reservar). */
interface BookedAddon {
  addon_id: string
  name: string
  unit_price: number
  quantity: number
  amount: number
}

export interface PublicStaff {
  public_id: string
  kind?: 'person' | 'resource'
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
  /** Servicios sumados al principal, en el orden elegido; ausente si no hay. */
  extra_service_ids?: string[]
  staff_id?: string
  starts_at: string
  notes?: string
  idempotency_key: string
  client_name: string
  /** Obligatorio en el portal (decision de Mateo, 2026-10-14). */
  client_email: string
  client_phone: string
  custom_fields?: Record<string, string>
  promotion_code?: string
  payment_method?: 'manual' | 'mercadopago'
  accepts_terms?: boolean
  /** Sin los adicionales en 0; vacio si no se eligio ninguno. */
  addons?: PublicBookingAddon[]
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
  /** Por donde se paga la seña obligatoria (null: no hay seña que pagar). */
  deposit_channel?: 'mercadopago' | 'whatsapp' | null
  /** Hasta cuándo se puede pagar la seña (ISO UTC); después el turno se libera. */
  deposit_deadline?: string | null
  payment_status?: string | null
  payment_link?: string | null
  payment_public_id?: string | null
  payment_amount?: number | null
  promotion_code?: string | null
  service_price?: number | null
  discount_amount?: number | null
  /** Total del turno: servicio (con promo) mas adicionales. */
  final_price?: number | null
  addons?: BookedAddon[]
  addons_amount?: number | null
  /** Servicios sumados al principal (vacio si no hay). */
  extra_services?: BookedExtraService[]
  /** "Corte + Barba"; ausente en una respuesta vieja. */
  services_label?: string | null
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
  /**
   * Solo `email`: es el unico canal con envio real. El backend acepta
   * `whatsapp`/`sms` unicamente con OTP_PROVIDER=console y en produccion los
   * rechaza con 422, asi que dejarlos en el tipo permitia volver a mandar un
   * canal que no funciona (fue el bug F11a-03, 2026-09-20). Cerrarlo en el
   * tipo lo vuelve un error de compilacion, no un test que alguien puede
   * borrar.
   */
  channel: 'email'
  email: string
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
  /**
   * Token del cliente (2026-10-14): la autogestion y el historial de la seña
   * lo exigen en `X-Client-Token`. Null si la verificacion no registro email.
   */
  client_token?: string | null
}

export interface WaitlistJoinPayload {
  store_public_id: string
  service_id: string
  staff_id?: string | null
  window_starts_at: string
  window_ends_at: string
  client_name: string
  client_phone: string
  client_email: string
  notes?: string | null
}

export interface PublicWaitlistEntry {
  public_id: string
  status: string
  service_name: string
  staff_name: string | null
  window_starts_at: string
  window_ends_at: string
}

export interface DepositPreview {
  amount: number
  base_amount: number
  extra_percent: number
  reasons: string[]
  /** Total sobre el que se calcula la seña: servicios mas adicionales, con la promo. */
  price: number
  addons_amount?: number
  /** Parte de `price` que son los servicios sumados al principal. */
  extra_services_amount?: number
  payments_enabled: boolean
  online_payment_mandatory: boolean
}

export interface ClientAppointmentItem {
  public_id: string
  /** `public_id` del servicio: con `staff_id`, pide la grilla para reprogramar. */
  service_id: string
  service_name: string
  /** Id publico del profesional, el mismo que usa la reserva publica. */
  staff_id: string
  staff_name: string
  starts_at: string
  ends_at: string
  status: string
  notes: string | null
  custom_fields: Record<string, string>
  can_cancel: boolean
  can_reschedule: boolean
  /** Servicios sumados al principal: la grilla para reprogramar los incluye. */
  extra_services?: BookedExtraService[]
  /** "Corte + Barba"; ausente en una respuesta vieja. */
  services_label?: string | null
}

export interface ClientAppointments {
  client_name: string
  client_phone: string
  appointments: ClientAppointmentItem[]
}

class PublicBookingService {
  /** Olvida el token del cliente ("Salir" o un 403 de verificacion). */
  forgetClientToken(): void {
    forgetClientToken()
  }

  async previewDeposit(params: {
    storePublicId: string
    serviceId: string
    startsAt: string
    clientPhone?: string
    promotionCode?: string
    /** `<id>:<cantidad>` por adicional elegido (`AddonSelection.toQueryParams`). */
    addons?: readonly string[]
    /** Servicios sumados al principal: la seña sale sobre el total del turno. */
    extraServiceIds?: readonly string[]
  }): Promise<DepositPreview> {
    const { data } = await apiClient.get<DepositPreview>('/public/deposit/preview', {
      params: {
        store_public_id: params.storePublicId,
        service_id: params.serviceId,
        starts_at: params.startsAt,
        client_phone: params.clientPhone || undefined,
        promotion_code: params.promotionCode || undefined,
        addon: params.addons?.length ? [...params.addons] : undefined,
        extra_service_id: extraServiceParam(params.extraServiceIds)
      },
      // El backend lee `addon` repetido (`addon=a:1&addon=b:2`); el formato por
      // defecto de axios mandaria `addon[]=...` y FastAPI no lo reconoce.
      paramsSerializer: { indexes: null },
      ...clientTokenConfig(params.storePublicId)
    })
    return data
  }

  async joinWaitlist(payload: WaitlistJoinPayload): Promise<PublicWaitlistEntry> {
    const { data } = await apiClient.post<PublicWaitlistEntry>('/public/waitlist', payload)
    return data
  }

  async getStore(slug: string): Promise<PublicStore> {
    const { data } = await apiClient.get<PublicStore>(`/public/stores/${slug}`)
    return data
  }

  async getStoreRef(slug: string): Promise<PublicStoreRef> {
    const { data } = await apiClient.get<PublicStoreRef>(`/public/stores/${slug}/ref`)
    return data
  }

  /**
   * `fresh`: saltea el cache del edge y del navegador. El edge cachea el
   * catalogo por URL completa (`proxy_cache_key $scheme$request_uri` en
   * nginx/nginx.prod.conf, s-maxage del backend) y no respeta un
   * `Cache-Control: no-cache` del pedido: un parametro que cambia en cada
   * pedido es lo que lo saltea. El backend ignora el parametro.
   */
  async getServices(
    storePublicId: string,
    options: { fresh?: boolean } = {}
  ): Promise<PublicService[]> {
    const { data } = await apiClient.get<PublicService[]>('/public/services', {
      params: options.fresh
        ? { store_public_id: storePublicId, fresh: Date.now() }
        : { store_public_id: storePublicId }
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
    forceAll = false,
    signal?: AbortSignal,
    /** Servicios sumados al principal: la grilla mide el turno entero. */
    extraServiceIds: readonly string[] = []
  ): Promise<AvailabilitySlot[]> {
    const { data } = await apiClient.get<AvailabilitySlot[]>('/public/availability', {
      params: {
        store_public_id: storePublicId,
        service_id: serviceId,
        date,
        force_all: forceAll,
        extra_service_id: extraServiceParam(extraServiceIds)
      },
      paramsSerializer: { indexes: null },
      signal
    })
    return data
  }

  async createBooking(payload: PublicBookingPayload): Promise<BookingConfirmation> {
    const config = clientTokenConfig(payload.store_public_id)
    const { data } = config
      ? await apiClient.post<BookingConfirmation>('/public/appointments', payload, config)
      : await apiClient.post<BookingConfirmation>('/public/appointments', payload)
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

  /**
   * La promo se mide contra el total (servicio + adicionales; decision de
   * Mateo, 2026-10-15): con `addons` (`<id>:<cantidad>`) el backend valida el
   * minimo y calcula el descuento sobre ese total.
   */
  async previewPromotion(
    storePublicId: string,
    serviceId: string,
    code: string,
    addons: readonly string[] = [],
    /** Servicios sumados al principal: la promo se mide contra el total. */
    extraServiceIds: readonly string[] = []
  ): Promise<PromotionPreview> {
    const { data } = await apiClient.get<PromotionPreview>('/public/promotions/preview', {
      params: {
        store_public_id: storePublicId,
        service_id: serviceId,
        code,
        addon: addons.length ? [...addons] : undefined,
        extra_service_id: extraServiceParam(extraServiceIds)
      },
      // `addon` repetido, sin corchetes (igual que el preview de la seña).
      paramsSerializer: { indexes: null }
    })
    return data
  }

  async getClientAppointments(storePublicId: string, phone: string): Promise<ClientAppointments> {
    // FF-05: sin limit el backend devuelve los 50 mas recientes (acepta 1..200);
    // se piden todos los que permite para no esconder turnos viejos.
    const { data } = await apiClient.get<ClientAppointments>(
      `/public/client/${storePublicId}/${phone}/appointments`,
      { params: { limit: 200 }, ...clientTokenConfig(storePublicId) }
    )
    return data
  }

  async cancelClientAppointment(
    storePublicId: string,
    publicId: string,
    phone: string
  ): Promise<void> {
    const url = `/public/client/appointments/${publicId}/cancel`
    // El token solo viaja a la tienda que lo emitio.
    const config = clientTokenConfig(storePublicId)
    if (config) await apiClient.patch(url, { phone }, config)
    else await apiClient.patch(url, { phone })
  }

  async rescheduleClientAppointment(payload: {
    storePublicId: string
    publicId: string
    phone: string
    newStartsAt: string
    idempotencyKey: string
  }): Promise<void> {
    const url = `/public/client/appointments/${payload.publicId}/reschedule`
    const body = {
      phone: payload.phone,
      new_starts_at: payload.newStartsAt,
      idempotency_key: payload.idempotencyKey
    }
    const config = clientTokenConfig(payload.storePublicId)
    if (config) await apiClient.patch(url, body, config)
    else await apiClient.patch(url, body)
  }

  async requestOtp(payload: OtpRequestPayload): Promise<OtpRequestResponse> {
    const { data } = await apiClient.post<OtpRequestResponse>('/public/otp/request', payload)
    return data
  }

  /**
   * Baja del mail promocional con el token firmado del link (pagina `/baja`).
   * Es POST a proposito: un escaner de correo que abre el link no da de baja.
   */
  async unsubscribeFromMarketing(token: string): Promise<void> {
    await apiClient.post('/public/unsubscribe', { token })
  }

  async verifyOtp(payload: OtpVerifyPayload): Promise<OtpVerifyResponse> {
    const { data } = await apiClient.post<OtpVerifyResponse>('/public/otp/verify', payload)
    rememberClientToken(payload.store_public_id, data.client_token)
    return data
  }
}

export const publicBookingService = new PublicBookingService()
