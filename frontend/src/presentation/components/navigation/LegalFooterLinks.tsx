import React from 'react'

import { Link } from 'react-router'

import { isAnalyticsConfigured } from '@infrastructure/analytics/bookingAnalytics'

import { openAnalyticsPreferences } from '@presentation/lib/analyticsPreferences'

import { colors2000s } from '../../../theme/colors'

interface LegalFooterLinksProps {
  /** Política propia de la tienda, cuando la publicó. */
  depositPolicy?: string | null
  /**
   * Muestra "Preferencias de analítica" (solo el portal de reservas, donde
   * corre Google Analytics). La Política de Privacidad remite a este enlace.
   */
  analyticsPreferences?: boolean
  className?: string
}

const FOOTER_LINK_CLASS =
  'inline-flex min-h-11 items-center rounded-md px-2 text-[10px] font-bold uppercase tracking-widest hover:underline'

/**
 * Enlaces legales del pie de página.
 *
 * Deben estar accesibles desde cualquier pantalla donde el cliente pueda
 * reservar o pagar: es lo que respalda a Shifty ante un reclamo.
 */
const LegalFooterLinks: React.FC<LegalFooterLinksProps> = ({
  depositPolicy,
  analyticsPreferences = false,
  className = ''
}) => (
  <div className={`flex flex-wrap items-center justify-center gap-x-1 gap-y-1 ${className}`}>
    <Link
      to="/legal/terminos"
      className="inline-flex min-h-11 items-center rounded-md px-2 text-[10px] font-bold uppercase tracking-widest hover:underline"
      style={{ color: colors2000s.text.secondary }}
    >
      Términos y condiciones
    </Link>
    <span
      aria-hidden="true"
      className="hidden text-[10px] sm:inline"
      style={{ color: colors2000s.text.disabled }}
    >
      ·
    </span>
    <Link
      to="/legal/privacidad"
      className="inline-flex min-h-11 items-center rounded-md px-2 text-[10px] font-bold uppercase tracking-widest hover:underline"
      style={{ color: colors2000s.text.secondary }}
    >
      Privacidad
    </Link>
    {analyticsPreferences && isAnalyticsConfigured() && (
      <>
        <span
          aria-hidden="true"
          className="hidden text-[10px] sm:inline"
          style={{ color: colors2000s.text.disabled }}
        >
          ·
        </span>
        <button
          type="button"
          className={FOOTER_LINK_CLASS}
          style={{ color: colors2000s.text.secondary }}
          onClick={openAnalyticsPreferences}
        >
          Preferencias de analítica
        </button>
      </>
    )}
    {depositPolicy && (
      <>
        <span
          aria-hidden="true"
          className="hidden text-[10px] sm:inline"
          style={{ color: colors2000s.text.disabled }}
        >
          ·
        </span>
        <span
          className="text-[10px] font-bold uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Política de seña publicada por la tienda
        </span>
      </>
    )}
  </div>
)

export default LegalFooterLinks
