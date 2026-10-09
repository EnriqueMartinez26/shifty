import apiClient from '@infrastructure/http/client'

export interface LedgerMovement {
  public_id: string
  movement_type: 'charge' | 'payment' | 'adjustment' | 'refund'
  amount: number
  balance_after: number
  appointment_id?: string | null
  notes?: string | null
  created_at: string
  /** El movimiento que esta reversion anula; null si no es una reversion. */
  reverses_id?: string | null
  /** Otro movimiento ya lo anulo: no se puede volver a revertir. */
  reversed?: boolean
}

/** Una pagina del historial, del movimiento mas nuevo al mas viejo. */
interface CustomerLedger {
  client_id: string
  balance: number
  /** Movimientos del cliente en total, no de esta pagina. */
  total: number
  movements: LedgerMovement[]
  /** Cursor de la pagina siguiente (`after`); `null` si no hay mas. */
  next_cursor: string | null
}

/** Cliente del buscador del fiado: el profesional recibe `email` null. */
export interface LedgerClient {
  public_id: string
  name: string
  email: string | null
  phone: string | null
}

interface LedgerSummaryClientItem {
  client_id: string
  client_name: string
  balance: number
  last_movement_at: string
}

export interface LedgerSummary {
  total_balance: number
  debtors_count: number
  average_balance: number
  total_movements: number
  top_debtors: LedgerSummaryClientItem[]
}

export interface LedgerMovementPayload {
  movement_type: 'charge' | 'payment' | 'adjustment' | 'refund'
  amount: number
  appointment_id?: string
  notes?: string
}

class LedgerService {
  // Nunca `offset`: combinado con `after` el backend responde 422.
  async getCustomerLedger(clientId: string, after?: string): Promise<CustomerLedger> {
    const { data } = await apiClient.get<CustomerLedger>(`/ledger/customers/${clientId}`, {
      params: { after }
    })
    return data
  }

  // `/users/` es solo del admin; este buscador sirve tambien al profesional.
  async searchClients(q?: string, signal?: AbortSignal): Promise<LedgerClient[]> {
    const { data } = await apiClient.get<LedgerClient[]>('/ledger/clients', {
      params: { q },
      signal
    })
    return data
  }

  async getSummary(): Promise<LedgerSummary> {
    const { data } = await apiClient.get<LedgerSummary>('/ledger/summary')
    return data
  }

  async addMovement(clientId: string, payload: LedgerMovementPayload): Promise<LedgerMovement> {
    const { data } = await apiClient.post<LedgerMovement>(
      `/ledger/customers/${clientId}/movements`,
      payload
    )
    return data
  }

  /**
   * Agrega el movimiento que anula a `movementId` (el original queda en el
   * historial). Sin cuerpo; 422 si ya fue revertido o si es una reversion.
   */
  async reverseMovement(clientId: string, movementId: string): Promise<LedgerMovement> {
    const { data } = await apiClient.post<LedgerMovement>(
      `/ledger/customers/${clientId}/movements/${movementId}/reverse`
    )
    return data
  }
}

export const ledgerService = new LedgerService()
