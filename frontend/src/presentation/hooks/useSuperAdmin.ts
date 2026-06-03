import { useQuery } from "@tanstack/react-query";

import {
  superAdminService,
  type ListStoresParams,
  type SuperAdminCoupon,
  type SuperAdminPlan,
  type SuperAdminStoreOverview,
  type SuperAdminStoreRow,
} from "@application/services/SuperAdminService";

export const useSuperAdminStores = (params: ListStoresParams) =>
  useQuery<SuperAdminStoreRow[]>({
    queryKey: ["superadmin", "stores", params],
    queryFn: () => superAdminService.listStores(params),
  });

export const useSuperAdminOverview = (storePublicId: string | null) =>
  useQuery<SuperAdminStoreOverview>({
    queryKey: ["superadmin", "overview", storePublicId],
    enabled: Boolean(storePublicId),
    queryFn: () => superAdminService.getStoreOverview(storePublicId as string),
  });

export const useSuperAdminPlans = () =>
  useQuery<SuperAdminPlan[]>({
    queryKey: ["superadmin", "plans"],
    queryFn: () => superAdminService.listPlans(false),
  });

export const useSuperAdminCoupons = () =>
  useQuery<SuperAdminCoupon[]>({
    queryKey: ["superadmin", "coupons"],
    queryFn: () => superAdminService.listCoupons(false),
  });
