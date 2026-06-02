import apiClient from "@infrastructure/http/client";

export interface LedgerMovement {
  public_id: string;
  movement_type: "charge" | "payment" | "adjustment" | "refund";
  amount: number;
  balance_after: number;
  appointment_id?: string | null;
  notes?: string | null;
  created_at: string;
}

export interface CustomerLedger {
  client_id: string;
  balance: number;
  movements: LedgerMovement[];
}

export interface LedgerMovementPayload {
  movement_type: "charge" | "payment" | "adjustment" | "refund";
  amount: number;
  appointment_id?: string;
  notes?: string;
}

export class LedgerService {
  async getCustomerLedger(clientId: string): Promise<CustomerLedger> {
    const { data } = await apiClient.get<CustomerLedger>(`/ledger/customers/${clientId}`);
    return data;
  }

  async addMovement(clientId: string, payload: LedgerMovementPayload): Promise<LedgerMovement> {
    const { data } = await apiClient.post<LedgerMovement>(`/ledger/customers/${clientId}/movements`, payload);
    return data;
  }
}

export const ledgerService = new LedgerService();
