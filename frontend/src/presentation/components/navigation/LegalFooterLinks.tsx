import React from 'react'

import { Link } from 'react-router'

import { colors2000s } from '../../../theme/colors'

interface LegalFooterLinksProps {
  /** Política propia de la tienda, cuando la publicó. */
  depositPolicy?: string | null
  className?: string
}

/**
 * Enlaces legales del pie de página.
 *
 * Deben estar accesibles desde cualquier pantalla donde el cliente pueda
 * reservar o pagar: es lo que respalda a Shifty ante un reclamo.
 */
export const LegalFooterLinks: React.FC<LegalFooterLinksProps> = ({
  depositPolicy,
  className = ''
}) => (
  <div className={`flex flex-wrap items-center justify-center gap-x-3 gap-y-1 ${className}`}>
    <Link
      to="/legal/terminos"
      className="text-[10px] font-bold uppercase tracking-widest hover:underline"
      style={{ color: colors2000s.text.secondary }}
    >
      Términos y condiciones
    </Link>
    <span className="text-[10px]" style={{ color: colors2000s.text.disabled }}>
      ·
    </span>
    <Link
      to="/legal/privacidad"
      className="text-[10px] font-bold uppercase tracking-widest hover:underline"
      style={{ color: colors2000s.text.secondary }}
    >
      Privacidad
    </Link>
    {depositPolicy && (
      <>
        <span className="text-[10px]" style={{ color: colors2000s.text.disabled }}>
          ·
        </span>
        <span
          className="text-[10px] font-bold uppercase tracking-widest"
          style={{ color: colors2000s.text.disabled }}
        >
          Política de seña publicada por la tienda
        </span>
      </>
    )}
  </div>
)

export default LegalFooterLinks
