import React, { useState } from 'react'

import type { CoverPosition } from '@application/services/StoreSettingsService'

import { coverObjectPosition } from './coverPosition'
import { brandCoverWash, type resolveBrandTheme } from '../../../lib/brandTheme'

type BrandTheme = ReturnType<typeof resolveBrandTheme>

interface StoreCoverProps {
  coverUrl: string | null | undefined
  /** Que parte de la foto se ve (S10.1); sin elegir, un poco abajo del medio. */
  coverPosition?: CoverPosition | null
  brand: BrandTheme
}

// Arriba de todo (S9): de borde a borde en el celular; en la compu ocupa el
// ancho del contenido y redondea solo abajo, porque toca el borde superior.
const COVER_SHAPE = 'w-full overflow-hidden sm:rounded-b-lg'

const CoverImage: React.FC<StoreCoverProps> = ({ coverUrl, coverPosition, brand }) => {
  const [failed, setFailed] = useState(false)
  if (coverUrl && !failed) {
    // Mas baja en el celular: el wizard sigue a la vista.
    return (
      <div className={`${COVER_SHAPE} h-[140px] sm:h-[232px]`}>
        <img
          src={coverUrl}
          alt=""
          decoding="async"
          onError={() => setFailed(true)}
          className="h-full w-full object-cover"
          style={{ objectPosition: coverObjectPosition(coverPosition) }}
        />
      </div>
    )
  }
  // Sin portada la franja solo anuncia el color: baja en el celular (S10.3).
  return (
    <div
      aria-hidden="true"
      data-testid="store-cover-band"
      className={`${COVER_SHAPE} h-16 sm:h-24`}
      style={{ background: brandCoverWash(brand) }}
    />
  )
}

/**
 * Portada del portal publico (S2, S9). Es decorativa; sin portada, o si no
 * carga (la CSP de produccion bloquea las URLs externas), un degradado suave
 * del color de la tienda.
 */
export const StoreCover: React.FC<StoreCoverProps> = ({ coverUrl, coverPosition, brand }) => (
  // key: otra portada vuelve a intentar cargar aunque la anterior fallara.
  <CoverImage
    key={coverUrl ?? ''}
    coverUrl={coverUrl}
    coverPosition={coverPosition}
    brand={brand}
  />
)
