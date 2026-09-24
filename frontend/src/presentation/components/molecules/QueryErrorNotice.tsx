import React from 'react'

import { colors2000s } from '../../../theme/colors'

interface QueryErrorNoticeProps {
  /** El `error` de la(s) query de la pantalla; null/undefined no renderiza nada. */
  error: unknown
  /** Mensaje neutro de la pantalla ("No se pudieron cargar ..."). */
  message: string
}

type ErrorWithCode = {
  context?: { errorCode?: unknown }
  originalError?: { context?: { errorCode?: unknown } }
}

/**
 * Un 403 FEATURE_DISABLED no es una falla: la funcion esta apagada para el
 * negocio. Llega como ApplicationError (servicios que usan apiClient directo)
 * o envuelto por BaseService en `originalError`.
 */
const isFeatureDisabled = (error: unknown): boolean => {
  const candidate = error as ErrorWithCode | null
  const code = candidate?.context?.errorCode ?? candidate?.originalError?.context?.errorCode
  return code === 'FEATURE_DISABLED'
}

/**
 * Aviso en linea de que un GET de la pantalla fallo, para que una consulta
 * caida no se lea como "no hay datos". Mismo tono que el error de Reportes;
 * el texto es neutro a proposito (regla 20: nada crudo del servidor).
 */
export const QueryErrorNotice: React.FC<QueryErrorNoticeProps> = ({ error, message }) => {
  if (!error) return null

  return (
    <div
      role="alert"
      className="text-sm p-4 rounded-lg font-bold"
      style={{
        background: colors2000s.status.danger.bg,
        border: `1px solid ${colors2000s.status.danger.border}`,
        color: colors2000s.status.danger.text,
        boxShadow: colors2000s.shadows.insetDark
      }}
    >
      {isFeatureDisabled(error) ? 'Esta función no está habilitada para tu negocio.' : message}
    </div>
  )
}
