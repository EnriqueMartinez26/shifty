import React from 'react'

import { RefreshCw } from 'lucide-react'

import { getHttpStatus } from '@shared/errors/getErrorMessage'

import { AuthShell } from './AuthShell'
import { buttonStyles2000s } from '../../../theme/colors'

/**
 * La tienda no existe (404, tambien con la vitrina suspendida) o la direccion
 * no puede ser de una (422 del slug). Sin red, un 429 o un 5xx son fallas
 * pasajeras: decir "no existe" ahi mandaba al cliente a buscar otro link.
 */
export const isStoreMissing = (error: unknown): boolean => {
  const status = getHttpStatus(error)
  return status === 404 || status === 422
}

interface StoreLoadErrorProps {
  onRetry: () => void
  retrying: boolean
}

/** La consulta de la tienda fallo por algo pasajero: texto neutro y reintento. */
export const StoreLoadError: React.FC<StoreLoadErrorProps> = ({ onRetry, retrying }) => (
  <AuthShell
    title="No pudimos cargar la tienda"
    subtitle="Puede ser un problema de conexión. Probá de nuevo en unos segundos."
  >
    <button
      type="button"
      onClick={onRetry}
      disabled={retrying}
      className="w-full font-bold py-4 rounded-2xl flex items-center justify-center gap-2 transition-all active:scale-[0.98]"
      style={retrying ? buttonStyles2000s.disabled : buttonStyles2000s.selected}
    >
      <RefreshCw className={`w-4 h-4 ${retrying ? 'animate-spin' : ''}`} aria-hidden="true" />
      {retrying ? 'Reintentando...' : 'Reintentar'}
    </button>
  </AuthShell>
)
