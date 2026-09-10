import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

import {
  storeSettingsService,
  type StoreFeatureFlags,
  type StoreFeatureFlagsResponse,
  type StoreMediaUploadResult,
  type StoreSettings,
  type StoreSubscriptionStatus,
  type StoreUpdatePayload
} from '@application/services/StoreSettingsService'

export const useStoreSettings = () =>
  useQuery<StoreSettings>({
    queryKey: ['store-settings'],
    queryFn: () => storeSettingsService.getSettings()
  })

export const useStoreSubscription = () =>
  useQuery<StoreSubscriptionStatus>({
    queryKey: ['store-subscription'],
    queryFn: () => storeSettingsService.getSubscription(),
    // El estado del plan cambia una vez por dia: no hace falta refrescarlo
    // en cada navegacion del panel.
    staleTime: 5 * 60 * 1000
  })

export const useUpdateStoreSettings = () => {
  const queryClient = useQueryClient()
  return useMutation<StoreSettings, Error, StoreUpdatePayload>({
    mutationFn: (payload) => storeSettingsService.updateSettings(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['store-settings'] })
    }
  })
}

export const useStoreFeatureFlags = () =>
  useQuery<StoreFeatureFlagsResponse>({
    queryKey: ['store-feature-flags'],
    queryFn: () => storeSettingsService.getFeatureFlags()
  })

export const useUpdateStoreFeatureFlags = () => {
  const queryClient = useQueryClient()
  return useMutation<StoreFeatureFlagsResponse, Error, Partial<StoreFeatureFlags>>({
    mutationFn: (payload) => storeSettingsService.updateFeatureFlags(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['store-feature-flags'] })
      void queryClient.invalidateQueries({ queryKey: ['store-settings'] })
    }
  })
}

export const useUploadStoreMedia = () => {
  const queryClient = useQueryClient()
  return useMutation<StoreMediaUploadResult, Error, { kind: 'logo' | 'cover'; file: File }>({
    mutationFn: ({ kind, file }) => storeSettingsService.uploadMedia(kind, file),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['store-settings'] })
    }
  })
}
