import apiClient from "@infrastructure/http/client";

export interface BudgetItem {
  public_id: string;
  title: string;
  improvement_description: string;
  estimated_hours: number;
  hourly_rate: number;
  currency: string;
  total_cost: number;
  status: string;
  notes: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface BudgetPayload {
  title: string;
  improvement_description: string;
  estimated_hours: number;
  hourly_rate: number;
  currency: string;
  status: string;
  notes?: string;
}

export class BudgetService {
  async list(includeInactive = false): Promise<BudgetItem[]> {
    const { data } = await apiClient.get<BudgetItem[]>(`/budget/?include_inactive=${includeInactive}`);
    return data;
  }

  async create(payload: BudgetPayload): Promise<BudgetItem> {
    const { data } = await apiClient.post<BudgetItem>("/budget/", payload);
    return data;
  }

  async update(publicId: string, payload: Partial<BudgetPayload>): Promise<BudgetItem> {
    const { data } = await apiClient.patch<BudgetItem>(`/budget/${publicId}`, payload);
    return data;
  }

  async delete(publicId: string): Promise<void> {
    await apiClient.delete(`/budget/${publicId}`);
  }
}

export const budgetService = new BudgetService();
