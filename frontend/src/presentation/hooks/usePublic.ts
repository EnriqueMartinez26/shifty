import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

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
  type PublicWaitlistEntry,
  type WaitlistJoinPayload
} from '@application/services/PublicBookingService'

export type {
  AvailabilitySlot,
  BookingConfirmation,
  OtpRequestPayload,
  OtpRequestResponse,
  OtpVerifyPayload,
  OtpVerifyResponse,
  PublicBookingPayload,
  PublicPaymentStatus,
  PromotionPreview,
  PublicService,
  PublicStaff,
  PublicStore
}

export const usePublicStore = (slug: string) =>
  useQuery<PublicStore>({
    queryKey: ['public-store', slug],
    queryFn: () => publicBookingService.getStore(slug),
    retry: false
  })

export const usePublicServices = (storePublicId: string | undefined) =>
  useQuery<PublicService[]>({
    queryKey: ['public-services', storePublicId],
    queryFn: () => publicBookingService.getServices(storePublicId as string),
    enabled: Boolean(storePublicId)
  })

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
    queryFn: () =>
      publicBookingService.getAvailability(
        storePublicId as string,
        serviceId as string,
        date as string,
        forceAll
      ),
    enabled: Boolean(storePublicId) && Boolean(serviceId) && Boolean(date),
    staleTime: 1000 * 30
  })

export const useCreatePublicBooking = () =>
  useMutation<BookingConfirmation, Error, PublicBookingPayload>({
    mutationFn: (payload) => publicBookingService.createBooking(payload)
  })

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
    }
  })
}

export const useJoinWaitlist = () =>
  useMutation<PublicWaitlistEntry, Error, WaitlistJoinPayload>({
    mutationFn: (payload) => publicBookingService.joinWaitlist(payload)
  })

export const usePublicPaymentStatus = (
  storePublicId: string | undefined,
  paymentPublicId: string | undefined
) =>
  useQuery<PublicPaymentStatus>({
    queryKey: ['public-payment-status', storePublicId, paymentPublicId],
    queryFn: () =>
      publicBookingService.getPaymentStatus(storePublicId as string, paymentPublicId as string),
    enabled: Boolean(storePublicId && paymentPublicId),
    refetchInterval: (query) => {
      const status = query.state.data?.payment_status
      return status === 'pending' ? 2000 : false
    },
    retry: 2
  })

export const usePreviewPublicPromotion = () =>
  useMutation<PromotionPreview, Error, { storePublicId: string; serviceId: string; code: string }>({
    mutationFn: ({ storePublicId, serviceId, code }) =>
      publicBookingService.previewPromotion(storePublicId, serviceId, code)
  })

export const useRequestPublicOtp = () =>
  useMutation<OtpRequestResponse, Error, OtpRequestPayload>({
    mutationFn: (payload) => publicBookingService.requestOtp(payload)
  })

export const useVerifyPublicOtp = () =>
  useMutation<OtpVerifyResponse, Error, OtpVerifyPayload>({
    mutationFn: (payload) => publicBookingService.verifyOtp(payload)
  })
