import {
  keepPreviousData,
  useInfiniteQuery,
  useMutation,
  useQuery,
  useQueryClient
} from '@tanstack/react-query'

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
  type SuperAdminAuditLog,
  type SuperAdminPlan,
  type SuperAdminStoreOverview,
  type SuperAdminSubscriptionOverview,
  type SuperAdminUser,
  type UpdateSuperAdminCouponPayload,
  type UpdateSuperAdminPlanPayload,
  type UpdateSuperAdminStorePayload,
  type UpdateSuperAdminUserPayload
} from '@application/services/SuperAdminService'

// El backend admite hasta 200; 50 era su corte fijo antes de paginar.
const STORES_PAGE_SIZE = 50

/**
 * Listado de tiendas por paginas con offset y total (FF-24). La clave no
 * lleva el offset: cambiar un filtro arranca de la primera pagina. El orden
 * del backend es solo `created_at`, asi que una tienda puede repetirse entre
 * paginas y se descarta por `public_id`.
 */
export const useSuperAdminStores = (params: Omit<ListStoresParams, 'limit' | 'offset'>) => {
  const query = useInfiniteQuery({
    queryKey: ['superadmin', 'stores', params],
    queryFn: ({ pageParam }) =>
      superAdminService.listStores({ ...params, limit: STORES_PAGE_SIZE, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (lastPage, pages) => {
      const loaded = pages.reduce((count, page) => count + page.stores.length, 0)
      // Sin total, una pagina llena quiere decir que puede haber mas.
      const hasMore =
        lastPage.total === null
          ? lastPage.stores.length === STORES_PAGE_SIZE
          : loaded < lastPage.total
      return hasMore && lastPage.stores.length > 0 ? loaded : undefined
    },
    placeholderData: keepPreviousData
  })
  const pages = query.data?.pages
  const seen = new Set<string>()
  const stores = pages
    ?.flatMap((page) => page.stores)
    .filter((store) => {
      if (seen.has(store.public_id)) return false
      seen.add(store.public_id)
      return true
    })
  return {
    data: stores,
    total: pages?.[pages.length - 1]?.total ?? null,
    hasNextPage: query.hasNextPage,
    fetchNextPage: query.fetchNextPage,
    isFetchingNextPage: query.isFetchingNextPage,
    isLoading: query.isLoading,
    isFetching: query.isFetching,
    error: query.error
  }
}

export const useSuperAdminOverview = (storePublicId: string | null) =>
  useQuery<SuperAdminStoreOverview>({
    queryKey: ['superadmin', 'overview', storePublicId],
    enabled: Boolean(storePublicId),
    queryFn: () => superAdminService.getStoreOverview(storePublicId as string)
  })

export const useSuperAdminStoreAudit = (storePublicId: string | null, limit = 15) =>
  useQuery<SuperAdminAuditLog[]>({
    queryKey: ['superadmin', 'audit', storePublicId, limit],
    enabled: Boolean(storePublicId),
    queryFn: () => superAdminService.getStoreAuditLogs(storePublicId as string, limit)
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
