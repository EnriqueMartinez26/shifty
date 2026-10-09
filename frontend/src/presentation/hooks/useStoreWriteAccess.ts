import { ERROR_CODE_MESSAGES } from '@shared/errors/errorCodes'

import { useStoreSubscription } from './useStores'
import { useAuth } from '../context/AuthContext'

interface StoreWriteAccess {
  /** Tienda suspendida: las escrituras bloqueadas se ven deshabilitadas. */
  readOnly: boolean
  /** Motivo para el `title` de cada accion deshabilitada. */
  reason: string
}

const SUSPENDED_REASON = ERROR_CODE_MESSAGES.get('SUBSCRIPTION_SUSPENDED') ?? ''

/**
 * Espejo en el panel de la guarda de suspension
 * (backend/modules/billing/dependencies.py, FF-15, D-20260930-10). Que accion
 * sigue permitida lo decide cada pantalla contra SUSPENSION_ALLOWED_WRITES.
 * Mientras el plan no cargo no bloquea: el 402 sigue siendo la red de
 * seguridad. El superadmin nunca queda en solo lectura, como en el backend.
 */
export const useStoreWriteAccess = (): StoreWriteAccess => {
  const { user } = useAuth()
  const { data: subscription } = useStoreSubscription()
  const readOnly = !user?.is_global_admin && subscription?.blocks_writes === true
  return { readOnly, reason: SUSPENDED_REASON }
}
