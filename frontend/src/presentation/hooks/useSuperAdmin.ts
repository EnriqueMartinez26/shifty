import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  superAdminService,
  type AssignSuperAdminSubscriptionPayload,
  type CreateSuperAdminCouponPayload,
  type CreateSuperAdminPlanPayload,
  type CreateSuperAdminStoreAdminPayload,
  type CreateSuperAdminStorePayload,
  type ListStoresParams,
  type SuperAdminCoupon,
  type SuperAdminCouponRedemption,
  type SuperAdminPlan,
  type SuperAdminStoreOverview,
  type SuperAdminStoreRow,
  type SuperAdminSubscriptionOverview,
  type SuperAdminUser,
  type UpdateSuperAdminCouponPayload,
  type UpdateSuperAdminPlanPayload,
  type UpdateSuperAdminStorePayload,
  type UpdateSuperAdminUserPayload
} from '@application/services/SuperAdminService'

export const useSuperAdminStores = (params: ListStoresParams) =>
  useQuery<SuperAdminStoreRow[]>({
    queryKey: ['superadmin', 'stores', params],
    queryFn: () => superAdminService.listStores(params)
  })

export const useSuperAdminOverview = (storePublicId: string | null) =>
  useQuery<SuperAdminStoreOverview>({
    queryKey: ['superadmin', 'overview', storePublicId],
    enabled: Boolean(storePublicId),
    queryFn: () => superAdminService.getStoreOverview(storePublicId as string)
  })

export const useSuperAdminPlans = (includeInactive = true) =>
  useQuery<SuperAdminPlan[]>({
    queryKey: ['superadmin', 'plans', includeInactive],
    queryFn: () => superAdminService.listPlans(includeInactive)
  })

export const useSuperAdminCoupons = (includeInactive = true) =>
  useQuery<SuperAdminCoupon[]>({
    queryKey: ['superadmin', 'coupons', includeInactive],
    queryFn: () => superAdminService.listCoupons(includeInactive)
  })

const useInvalidateSuperAdmin = () => {
  const queryClient = useQueryClient()
  return () => queryClient.invalidateQueries({ queryKey: ['superadmin'] })
}

export const useCreateSuperAdminStore = () => {
  const invalidateSuperAdmin = useInvalidateSuperAdmin()
  return useMutation({
    mutationFn: (payload: CreateSuperAdminStorePayload) => superAdminService.createStore(payload),
    onSuccess: () => invalidateSuperAdmin()
  })
}

export const useUpdateSuperAdminStore = () => {
  const invalidateSuperAdmin = useInvalidateSuperAdmin()
  return useMutation({
    mutationFn: ({
      storePublicId,
      payload
    }: {
      storePublicId: string
      payload: UpdateSuperAdminStorePayload
    }) => superAdminService.updateStore(storePublicId, payload),
    onSuccess: () => invalidateSuperAdmin()
  })
}

export const useCreateSuperAdminStoreAdmin = () => {
  const invalidateSuperAdmin = useInvalidateSuperAdmin()
  return useMutation({
    mutationFn: ({
      storePublicId,
      payload
    }: {
      storePublicId: string
      payload: CreateSuperAdminStoreAdminPayload
    }) => superAdminService.createStoreAdmin(storePublicId, payload),
    onSuccess: () => invalidateSuperAdmin()
  })
}

export const useUpdateSuperAdminUser = () => {
  const invalidateSuperAdmin = useInvalidateSuperAdmin()
  return useMutation({
    mutationFn: ({
      userPublicId,
      payload
    }: {
      userPublicId: string
      payload: UpdateSuperAdminUserPayload
    }) => superAdminService.updateUser(userPublicId, payload),
    onSuccess: () => invalidateSuperAdmin()
  })
}

export const useSetSuperAdminGlobalAdmin = () => {
  const invalidateSuperAdmin = useInvalidateSuperAdmin()
  return useMutation<SuperAdminUser, Error, { userPublicId: string; isGlobalAdmin: boolean }>({
    mutationFn: ({ userPublicId, isGlobalAdmin }) =>
      superAdminService.setGlobalAdmin(userPublicId, isGlobalAdmin),
    onSuccess: () => invalidateSuperAdmin()
  })
}

export const useCreateSuperAdminPlan = () => {
  const invalidateSuperAdmin = useInvalidateSuperAdmin()
  return useMutation({
    mutationFn: (payload: CreateSuperAdminPlanPayload) => superAdminService.createPlan(payload),
    onSuccess: () => invalidateSuperAdmin()
  })
}

export const useUpdateSuperAdminPlan = () => {
  const invalidateSuperAdmin = useInvalidateSuperAdmin()
  return useMutation({
    mutationFn: ({
      planPublicId,
      payload
    }: {
      planPublicId: string
      payload: UpdateSuperAdminPlanPayload
    }) => superAdminService.updatePlan(planPublicId, payload),
    onSuccess: () => invalidateSuperAdmin()
  })
}

export const useAssignSuperAdminSubscription = () => {
  const invalidateSuperAdmin = useInvalidateSuperAdmin()
  return useMutation<
    SuperAdminSubscriptionOverview,
    Error,
    { storePublicId: string; payload: AssignSuperAdminSubscriptionPayload }
  >({
    mutationFn: ({ storePublicId, payload }) =>
      superAdminService.assignSubscription(storePublicId, payload),
    onSuccess: () => invalidateSuperAdmin()
  })
}

export const useCreateSuperAdminCoupon = () => {
  const invalidateSuperAdmin = useInvalidateSuperAdmin()
  return useMutation({
    mutationFn: (payload: CreateSuperAdminCouponPayload) => superAdminService.createCoupon(payload),
    onSuccess: () => invalidateSuperAdmin()
  })
}

export const useUpdateSuperAdminCoupon = () => {
  const invalidateSuperAdmin = useInvalidateSuperAdmin()
  return useMutation({
    mutationFn: ({
      couponPublicId,
      payload
    }: {
      couponPublicId: string
      payload: UpdateSuperAdminCouponPayload
    }) => superAdminService.updateCoupon(couponPublicId, payload),
    onSuccess: () => invalidateSuperAdmin()
  })
}

export const useRedeemSuperAdminCoupon = () => {
  const invalidateSuperAdmin = useInvalidateSuperAdmin()
  return useMutation<
    SuperAdminCouponRedemption,
    Error,
    { storePublicId: string; couponCode: string }
  >({
    mutationFn: ({ storePublicId, couponCode }) =>
      superAdminService.redeemCoupon(storePublicId, couponCode),
    onSuccess: () => invalidateSuperAdmin()
  })
}
