import { useState } from 'react'

import { queryOptions, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  publicBookingService,
  type AvailabilitySlot,
  type BookingConfirmation,
  type ClientAppointments,
  type DepositPreview,
  type OtpRequestPayload,
  type OtpRequestResponse,
  type OtpVerifyPayload,
  type OtpVerifyResponse,
  type PublicBookingPayload,
  type PublicPaymentStatus,
  type PromotionPreview,
  type PublicService,
  type PublicStaff,
  type PublicStore,
  type PublicStoreRef,
  type PublicWaitlistEntry,
  type WaitlistJoinPayload
} from '@application/services/PublicBookingService'

import { getRetryAfterSeconds } from '@shared/errors/getErrorMessage'

import { PAYMENT_POLL_MAX_MS, paymentPollDelayMs } from '../lib/paymentPolling'

export type { PublicStore }

// Clave, queryFn y retry de la tienda y sus servicios viven en un solo lugar:
// el prefetch del portal (lib/portalPrefetch.ts, F4-14) usa las mismas y una
// clave distinta repetiria la request al montar la pagina.
export const publicStoreQuery = (slug: string) =>
  queryOptions<PublicStore>({
    queryKey: ['public-store', slug],
    queryFn: () => publicBookingService.getStore(slug),
    retry: false
  })

export const publicStoreRefQuery = (slug: string) =>
  queryOptions<PublicStoreRef>({
    queryKey: ['public-store-ref', slug],
    queryFn: () => publicBookingService.getStoreRef(slug),
    retry: false
  })

export const publicServicesQuery = (storePublicId: string | undefined) =>
  queryOptions<PublicService[]>({
    queryKey: ['public-services', storePublicId],
    queryFn: () => publicBookingService.getServices(storePublicId as string)
  })

export const usePublicStore = (slug: string, enabled = true) =>
  useQuery({ ...publicStoreQuery(slug), enabled })

/** "Mis turnos" resuelve la tienda por aca: la vitrina da 404 si esta suspendida (FF-16). */
export const usePublicStoreRef = (slug: string) => useQuery(publicStoreRefQuery(slug))

export const usePublicServices = (storePublicId: string | undefined) =>
  useQuery({ ...publicServicesQuery(storePublicId), enabled: Boolean(storePublicId) })

export const usePublicStaff = (storePublicId: string | undefined, serviceId?: string) =>
  useQuery<PublicStaff[]>({
    queryKey: ['public-staff', storePublicId, serviceId],
    queryFn: () => publicBookingService.getStaff(storePublicId as string, serviceId),
    enabled: Boolean(storePublicId)
  })

export const usePublicAvailability = (
  storePublicId: string | undefined,
  serviceId: string | undefined,
  date: string | undefined,
  forceAll = false
) =>
  useQuery<AvailabilitySlot[]>({
    queryKey: ['public-availability', storePublicId, serviceId, date, forceAll],
    // Con el signal, cambiar de dia cancela la grilla del dia anterior (F4-04).
    queryFn: ({ signal }) =>
      publicBookingService.getAvailability(
        storePublicId as string,
        serviceId as string,
        date as string,
        forceAll,
        signal
      ),
    enabled: Boolean(storePublicId) && Boolean(serviceId) && Boolean(date),
    staleTime: 1000 * 30
  })

export const useCreatePublicBooking = () => {
  const queryClient = useQueryClient()
  return useMutation<BookingConfirmation, Error, PublicBookingPayload>({
    mutationFn: (payload) => publicBookingService.createBooking(payload),
    // Con o sin exito la grilla quedo vieja: con staleTime de 30 s el horario
    // tomado seguia libre al volver al paso 2 (FF-33). El paso 2 esta
    // desmontado y su consulta inactiva: sin `refetchType: 'all'` no se pedia.
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['public-availability'], refetchType: 'all' })
    }
  })
}

/** La seña real (con recargos por antelación e historial) antes de confirmar. */
export const usePublicDepositPreview = (params: {
  storePublicId: string
  serviceId: string
  startsAt: string | null
  clientPhone?: string
  promotionCode?: string
}) =>
  useQuery<DepositPreview>({
    queryKey: [
      'public-deposit-preview',
      params.storePublicId,
      params.serviceId,
      params.startsAt,
      params.clientPhone,
      params.promotionCode
    ],
    enabled: Boolean(params.storePublicId && params.serviceId && params.startsAt),
    // Al completar el telefono o aplicar un codigo cambia la clave: sin la seña
    // anterior mientras carga, el boton de Mercado Pago parpadeaba (FF-32). Solo
    // para el MISMO turno: con otro horario la seña vieja pasaba por actual.
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[1] === params.storePublicId &&
      previousQuery.queryKey[2] === params.serviceId &&
      previousQuery.queryKey[3] === params.startsAt
        ? previous
        : undefined,
    queryFn: () =>
      publicBookingService.previewDeposit({
        storePublicId: params.storePublicId,
        serviceId: params.serviceId,
        startsAt: params.startsAt as string,
        clientPhone: params.clientPhone,
        promotionCode: params.promotionCode
      })
  })

export const usePublicClientAppointments = (
  storePublicId: string | undefined,
  phone: string,
  enabled: boolean
) =>
  useQuery<ClientAppointments>({
    queryKey: ['public-client-appointments', storePublicId, phone],
    enabled: Boolean(storePublicId && phone && enabled),
    retry: false,
    queryFn: () => publicBookingService.getClientAppointments(storePublicId as string, phone)
  })

export const useCancelClientAppointment = () => {
  const queryClient = useQueryClient()
  return useMutation<void, Error, { publicId: string; phone: string }>({
    mutationFn: ({ publicId, phone }) =>
      publicBookingService.cancelClientAppointment(publicId, phone),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['public-client-appointments'] })
    }
  })
}

export const useRescheduleClientAppointment = () => {
  const queryClient = useQueryClient()
  return useMutation<
    void,
    Error,
    { publicId: string; phone: string; newStartsAt: string; idempotencyKey: string }
  >({
    mutationFn: (payload) => publicBookingService.rescheduleClientAppointment(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['public-client-appointments'] })
      void queryClient.invalidateQueries({ queryKey: ['public-availability'] })
    },
    // Un 409 (horario tomado, bloqueado) deja la grilla vieja: se vuelve a
    // pedir para no seguir ofreciendo ese horario (FF-06, mismo patron que
    // FF-33 en useCreatePublicBooking).
    onError: () => {
      void queryClient.invalidateQueries({ queryKey: ['public-availability'], refetchType: 'all' })
    }
  })
}

export const useJoinWaitlist = () =>
  useMutation<PublicWaitlistEntry, Error, WaitlistJoinPayload>({
    mutationFn: (payload) => publicBookingService.joinWaitlist(payload)
  })

/**
 * Estado del pago al volver de Mercado Pago. Mientras sigue pendiente se
 * sondea con backoff y se corta a los 30 min (F4-05); `pollingStopped` avisa
 * el corte. El front nunca da el turno por confirmado: eso lo decide el
 * webhook (regla 7). Sin `retry` propio: rige la politica global (main.tsx),
 * que no repite un 429.
 */
export const usePublicPaymentStatus = (
  storePublicId: string | undefined,
  paymentPublicId: string | undefined
) => {
  const [startedAt] = useState(() => Date.now())
  const query = useQuery<PublicPaymentStatus>({
    queryKey: ['public-payment-status', storePublicId, paymentPublicId],
    queryFn: () =>
      publicBookingService.getPaymentStatus(storePublicId as string, paymentPublicId as string),
    enabled: Boolean(storePublicId && paymentPublicId),
    refetchInterval: (q) =>
      q.state.data?.payment_status === 'pending'
        ? paymentPollDelayMs(Date.now() - startedAt, getRetryAfterSeconds(q.state.error))
        : false
  })
  // Se deriva del reloj en cada render. La ultima consulta sale en el corte o
  // despues (la espera previa es de 15 s) y su respuesta re-renderiza porque
  // el spread de abajo lee, y suscribe, todas las propiedades del resultado
  // (`dataUpdatedAt` incluida): con solo `data` una respuesta igual no
  // renderizaba y el aviso no aparecia nunca.
  const pollingStopped =
    query.data?.payment_status === 'pending' && Date.now() - startedAt >= PAYMENT_POLL_MAX_MS
  return { ...query, pollingStopped }
}

export const usePreviewPublicPromotion = () =>
  useMutation<PromotionPreview, Error, { storePublicId: string; serviceId: string; code: string }>({
    mutationFn: ({ storePublicId, serviceId, code }) =>
      publicBookingService.previewPromotion(storePublicId, serviceId, code)
  })

export const useRequestPublicOtp = () =>
  useMutation<OtpRequestResponse, Error, OtpRequestPayload>({
    mutationFn: (payload) => publicBookingService.requestOtp(payload)
  })

export const useUnsubscribeFromMarketing = () =>
  useMutation<void, Error, string>({
    mutationFn: (token) => publicBookingService.unsubscribeFromMarketing(token)
  })

export const useVerifyPublicOtp = () =>
  useMutation<OtpVerifyResponse, Error, OtpVerifyPayload>({
    mutationFn: (payload) => publicBookingService.verifyOtp(payload)
  })
