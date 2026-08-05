import { useMutation, useQuery } from '@tanstack/react-query'

import {
  publicBookingService,
  type AvailabilitySlot,
  type BookingConfirmation,
  type OtpRequestPayload,
  type OtpRequestResponse,
  type OtpVerifyPayload,
  type OtpVerifyResponse,
  type PublicBookingPayload,
  type PublicPaymentStatus,
  type PromotionPreview,
  type PublicService,
  type PublicStaff,
  type PublicStore
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
