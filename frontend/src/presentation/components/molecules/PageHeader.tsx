import React from 'react'

import { Loader2 } from 'lucide-react'

import { colors2000s } from '../../../theme/colors'
import { create2000sPanelStyle } from '../../lib/surfaceStyles'

interface PageHeaderProps {
  title: string
  description: string
  isLoading: boolean
  loadingText: string
}

/**
 * Encabezado de las pantallas operativas (Cobros, Cobros online, Promociones,
 * Cuentas pendientes): titulo, bajada y el indicador de carga a la derecha.
 */
export const PageHeader: React.FC<PageHeaderProps> = ({
  title,
  description,
  isLoading,
  loadingText
}) => (
  <div
    className="p-6 rounded-3xl flex flex-wrap items-start justify-between gap-4"
    style={create2000sPanelStyle()}
  >
    <div>
      <h2
        className="text-2xl font-black uppercase tracking-tight"
        style={{ color: colors2000s.text.primary }}
      >
        {title}
      </h2>
      <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
        {description}
      </p>
    </div>
    {isLoading && (
      <div
        className="flex items-center gap-2 text-xs font-black uppercase tracking-widest"
        style={{ color: colors2000s.text.secondary }}
      >
        <Loader2 className="w-4 h-4 animate-spin" />
        {loadingText}
      </div>
    )}
  </div>
)
