import React, { useState } from 'react'

import { colors2000s } from '../../../../theme/colors'
import type { resolveBrandTheme } from '../../../lib/brandTheme'
import { computeLogoScale } from '../../../lib/logoFit'

type BrandTheme = ReturnType<typeof resolveBrandTheme>

// Logo redondo con aro blanco que pisa el borde inferior de la portada por la
// mitad de su alto (76 px en el celular, 112 px en la compu).
const LOGO_BOX =
  'h-[76px] w-[76px] -mt-[38px] shrink-0 rounded-full border-4 border-white sm:h-28 sm:w-28 sm:-mt-14'
const LOGO_SHADOW = { boxShadow: colors2000s.shadows.outer }

// Lado del lienzo de medicion: sobra para encontrar el margen y es barato.
const SAMPLE_SIDE = 256

const isSameOrigin = (src: string): boolean => {
  try {
    return new URL(src, window.location.href).origin === window.location.origin
  } catch {
    return false
  }
}

/**
 * Cuanto agrandar el logo para que llene el circulo (S10.2). Solo con un logo
 * del mismo origen (los que sube la tienda): uno de otro sitio dejaria el
 * lienzo manchado. Ante cualquier falla, 1: el logo queda como estaba.
 */
const measureLogoScale = (img: HTMLImageElement): number => {
  try {
    if (!isSameOrigin(img.currentSrc || img.src)) return 1
    const side = Math.max(img.naturalWidth, img.naturalHeight)
    if (side === 0) return 1
    const ratio = Math.min(1, SAMPLE_SIDE / side)
    const width = Math.max(1, Math.round(img.naturalWidth * ratio))
    const height = Math.max(1, Math.round(img.naturalHeight * ratio))
    const canvas = document.createElement('canvas')
    canvas.width = width
    canvas.height = height
    const context = canvas.getContext('2d', { willReadFrequently: true })
    if (!context) return 1
    context.drawImage(img, 0, 0, width, height)
    return computeLogoScale(context.getImageData(0, 0, width, height))
  } catch {
    return 1
  }
}

/**
 * La imagen no se ve hasta medirla: aparece de una vez con su escala, sin
 * saltar de tamano. Mientras carga se ve el circulo blanco con su aro.
 */
const LogoImage: React.FC<{ name: string; logoUrl: string; onError: () => void }> = ({
  name,
  logoUrl,
  onError
}) => {
  const [scale, setScale] = useState<number | null>(null)
  return (
    <span className={`${LOGO_BOX} block overflow-hidden bg-white`} style={LOGO_SHADOW}>
      <img
        src={logoUrl}
        alt={`Logo de ${name}`}
        width={112}
        height={112}
        decoding="async"
        onLoad={(event) => setScale(measureLogoScale(event.currentTarget))}
        onError={onError}
        className="h-full w-full object-contain"
        style={{
          opacity: scale === null ? 0 : 1,
          transform: scale !== null && scale > 1 ? `scale(${scale})` : undefined
        }}
      />
    </span>
  )
}

/**
 * Logo de la tienda; sin logo, o si la imagen no carga (la CSP de produccion
 * bloquea las URLs externas), la inicial del nombre en el color de marca.
 */
export const StoreLogo: React.FC<{
  name: string
  logoUrl: string | null | undefined
  brand: BrandTheme
}> = ({ name, logoUrl, brand }) => {
  const [failed, setFailed] = useState(false)
  if (logoUrl && !failed) {
    return <LogoImage name={name} logoUrl={logoUrl} onError={() => setFailed(true)} />
  }
  const initial = Array.from(name.trim())[0]?.toLocaleUpperCase('es-AR') ?? ''
  return (
    <span
      aria-hidden="true"
      className={`${LOGO_BOX} flex items-center justify-center text-3xl font-black sm:text-5xl`}
      style={{ ...LOGO_SHADOW, background: brand.fill, color: brand.onFill }}
    >
      {initial}
    </span>
  )
}
