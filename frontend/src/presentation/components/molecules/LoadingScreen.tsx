import React from 'react'

import { Loader2 } from 'lucide-react'

import { colors2000s } from '../../../theme/colors'

/**
 * Pantalla completa mientras carga un chunk o se valida la sesion. Antes era
 * un "Cargando..." suelto arriba a la izquierda, sin fondo: con la API caida
 * era lo unico que se veia (QA en navegador, 2026-10-02).
 */
export const LoadingScreen: React.FC = () => (
  <div
    role="status"
    aria-live="polite"
    className="min-h-screen w-full flex items-center justify-center px-4"
    style={{
      background: `linear-gradient(180deg, ${colors2000s.bg.primary} 0%, ${colors2000s.bg.secondary} 100%)`
    }}
  >
    <span
      className="inline-flex items-center gap-3 text-xs font-black uppercase tracking-widest"
      style={{ color: colors2000s.text.secondary }}
    >
      <Loader2
        className="w-5 h-5 animate-spin"
        style={{ color: colors2000s.orange.accent }}
        aria-hidden="true"
      />
      Cargando...
    </span>
  </div>
)
