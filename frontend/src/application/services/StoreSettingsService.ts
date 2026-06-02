import apiClient from "@infrastructure/http/client";
import type { BusinessType } from "@presentation/lib/businessLabels";

export interface BusinessHourPeriod {
  open: string;
  close: string;
}

export interface StoreFeatureFlags {
  payments: boolean;
  ledger: boolean;
  advanced_reports: boolean;
  new_calendar: boolean;
  otp_booking: boolean;
}

export interface StoreSettings {
  public_id: string;
  name: string;
  slug: string;
  business_type: BusinessType;
  logo_url: string | null;
  primary_color: string;
  cover_url?: string | null;
  description?: string | null;
  whatsapp_number?: string | null;
  instagram_url?: string | null;
  facebook_url?: string | null;
  website_url?: string | null;
  cancellation_hours: number;
  buffer_minutes: number;
  business_hours: Record<string, BusinessHourPeriod[]>;
  send_email_confirmation: boolean;
  send_email_reminders: boolean;
  feature_flags?: StoreFeatureFlags;
}

export interface StoreUpdatePayload {
  name?: string;
  slug?: string;
  business_type?: BusinessType;
  logo_url?: string | null;
  primary_color?: string;
  cover_url?: string | null;
  description?: string | null;
  whatsapp_number?: string | null;
  instagram_url?: string | null;
  facebook_url?: string | null;
  website_url?: string | null;
  cancellation_hours?: number;
  buffer_minutes?: number;
  business_hours?: Record<string, BusinessHourPeriod[]>;
  send_email_confirmation?: boolean;
  send_email_reminders?: boolean;
}

export interface StoreFeatureFlagsResponse {
  flags: StoreFeatureFlags;
}

export class StoreSettingsService {
  async getSettings(): Promise<StoreSettings> {
    const { data } = await apiClient.get<StoreSettings>("/stores/me");
    return data;
  }

  async updateSettings(payload: StoreUpdatePayload): Promise<StoreSettings> {
    const { data } = await apiClient.patch<StoreSettings>("/stores/me", payload);
    return data;
  }

  async getFeatureFlags(): Promise<StoreFeatureFlagsResponse> {
    const { data } = await apiClient.get<StoreFeatureFlagsResponse>("/stores/me/feature-flags");
    return data;
  }

  async updateFeatureFlags(payload: Partial<StoreFeatureFlags>): Promise<StoreFeatureFlagsResponse> {
    const { data } = await apiClient.put<StoreFeatureFlagsResponse>("/stores/me/feature-flags", payload);
    return data;
  }
}

export const storeSettingsService = new StoreSettingsService();
