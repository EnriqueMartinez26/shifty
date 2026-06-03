import apiClient from "@infrastructure/http/client";

export interface SuperAdminStoreRow {
  public_id: string;
  name: string;
  slug: string;
  logo_url: string | null;
  primary_color: string;
  cancellation_hours: number;
  buffer_minutes: number;
  send_email_confirmation: boolean;
  send_email_reminders: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  admins_count: number;
  users_count: number;
  active_users_count: number;
  has_subscription: boolean;
  subscription_status: string | null;
  current_plan_name: string | null;
  current_period_end: string | null;
  last_redemption_at: string | null;
}

export interface SuperAdminUser {
  public_id: string;
  email: string;
  first_name: string | null;
  last_name: string | null;
  phone: string | null;
  role: "admin" | "staff" | "receptionist" | "client";
  store_id: string;
  is_active: boolean;
  is_global_admin: boolean;
  created_at: string;
  updated_at: string;
}

export interface SuperAdminAppliedCoupon {
  public_id: string;
  code: string;
  coupon_type: string;
  value: string;
  currency: string | null;
  is_active: boolean;
}

export interface SuperAdminSubscriptionOverview {
  public_id: string;
  store_id: string;
  plan_id: string;
  status: string;
  base_amount: string;
  discount_amount: string;
  total_amount: string;
  currency: string;
  current_period_start: string | null;
  current_period_end: string | null;
  coupon_id: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  plan_name: string | null;
  billing_interval: string | null;
  max_staff: number | null;
  max_services: number | null;
  applied_coupon: SuperAdminAppliedCoupon | null;
}

export interface SuperAdminUsersOverview {
  admins: SuperAdminUser[];
  users: SuperAdminUser[];
  admins_count: number;
  users_count: number;
  active_users_count: number;
}

export interface SuperAdminCouponRedemption {
  public_id: string;
  coupon_id: string;
  store_id: string;
  subscription_id: string | null;
  redeemed_by_id: string | null;
  code_snapshot: string;
  coupon_type_snapshot: string;
  value_snapshot: string;
  base_amount: string;
  discount_amount: string;
  final_amount: string;
  currency: string;
  created_at: string;
}

export interface SuperAdminStoreOverview {
  store: Omit<SuperAdminStoreRow, "admins_count" | "users_count" | "active_users_count" | "has_subscription" | "subscription_status" | "current_plan_name" | "current_period_end" | "last_redemption_at">;
  users: SuperAdminUsersOverview;
  subscription: SuperAdminSubscriptionOverview | null;
  recent_redemptions: SuperAdminCouponRedemption[];
}

export interface SuperAdminPlan {
  public_id: string;
  name: string;
  description: string | null;
  price: string;
  currency: string;
  billing_interval: string;
  max_staff: number | null;
  max_services: number | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface SuperAdminCoupon {
  public_id: string;
  code: string;
  coupon_type: string;
  value: string;
  currency: string | null;
  max_uses: number | null;
  current_uses: number;
  valid_from: string | null;
  valid_until: string | null;
  one_time_per_store: boolean;
  description: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface ListStoresParams {
  search?: string;
  is_active?: boolean | null;
  has_subscription?: boolean | null;
}

export class SuperAdminService {
  async listStores(params: ListStoresParams = {}): Promise<SuperAdminStoreRow[]> {
    const searchParams = new URLSearchParams();
    if (params.search) searchParams.set("search", params.search);
    if (params.is_active !== undefined && params.is_active !== null) {
      searchParams.set("is_active", String(params.is_active));
    }
    if (params.has_subscription !== undefined && params.has_subscription !== null) {
      searchParams.set("has_subscription", String(params.has_subscription));
    }
    const query = searchParams.toString();
    const { data } = await apiClient.get<SuperAdminStoreRow[]>(`/superadmin/stores${query ? `?${query}` : ""}`);
    return data;
  }

  async getStoreOverview(storePublicId: string): Promise<SuperAdminStoreOverview> {
    const { data } = await apiClient.get<SuperAdminStoreOverview>(`/superadmin/stores/${storePublicId}/overview`);
    return data;
  }

  async listPlans(includeInactive = false): Promise<SuperAdminPlan[]> {
    const { data } = await apiClient.get<SuperAdminPlan[]>(`/superadmin/plans?include_inactive=${includeInactive}`);
    return data;
  }

  async listCoupons(includeInactive = false): Promise<SuperAdminCoupon[]> {
    const { data } = await apiClient.get<SuperAdminCoupon[]>(`/superadmin/coupons?include_inactive=${includeInactive}`);
    return data;
  }
}

export const superAdminService = new SuperAdminService();
