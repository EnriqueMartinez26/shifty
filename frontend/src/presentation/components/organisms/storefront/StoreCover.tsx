import React, { useState } from 'react'

import type { resolveBrandTheme } from '../../../lib/brandTheme'

type BrandTheme = ReturnType<typeof resolveBrandTheme>

interface StoreCoverProps {
  coverUrl: string | null | undefined
  brand: BrandTheme
}

const CoverImage: React.FC<StoreCoverProps> = ({ coverUrl, brand }) => {
  const [failed, setFailed] = useState(false)
  if (coverUrl && !failed) {
    // 3:1 con tope de alto: en un telefono el wizard sigue a la vista.
    return (
      <div className="mx-auto aspect-[3/1] max-h-48 w-full max-w-2xl overflow-hidden rounded-lg">
        <img
          src={coverUrl}
          alt=""
          decoding="async"
          onError={() => setFailed(true)}
          className="h-full w-full object-cover"
        />
      </div>
    )
  }
  return (
    <div
      aria-hidden="true"
      data-testid="store-cover-band"
      className="mx-auto h-2.5 w-full max-w-2xl rounded-full"
      style={{ background: brand.fill }}
    />
  )
}

/**
 * Portada del portal publico (S2). Es decorativa; sin portada, o si no carga
 * (la CSP de produccion bloquea las URLs externas), una franja del color de
 * la tienda.
 */
export const StoreCover: React.FC<StoreCoverProps> = ({ coverUrl, brand }) => (
  // key: otra portada vuelve a intentar cargar aunque la anterior fallara.
  <CoverImage key={coverUrl ?? ''} coverUrl={coverUrl} brand={brand} />
)
