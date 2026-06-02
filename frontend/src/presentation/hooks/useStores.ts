import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
    storeSettingsService,
    type StoreFeatureFlags,
    type StoreFeatureFlagsResponse,
    type StoreSettings,
    type StoreUpdatePayload,
} from "@application/services/StoreSettingsService";

export const useStoreSettings = () =>
    useQuery<StoreSettings>({
        queryKey: ["store-settings"],
        queryFn: () => storeSettingsService.getSettings(),
    });

export const useUpdateStoreSettings = () => {
    const queryClient = useQueryClient();
    return useMutation<StoreSettings, Error, StoreUpdatePayload>({
        mutationFn: (payload) => storeSettingsService.updateSettings(payload),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["store-settings"] });
        },
    });
};

export const useStoreFeatureFlags = () =>
    useQuery<StoreFeatureFlagsResponse>({
        queryKey: ["store-feature-flags"],
        queryFn: () => storeSettingsService.getFeatureFlags(),
    });

export const useUpdateStoreFeatureFlags = () => {
    const queryClient = useQueryClient();
    return useMutation<StoreFeatureFlagsResponse, Error, Partial<StoreFeatureFlags>>({
        mutationFn: (payload) => storeSettingsService.updateFeatureFlags(payload),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ["store-feature-flags"] });
            queryClient.invalidateQueries({ queryKey: ["store-settings"] });
        },
    });
};
