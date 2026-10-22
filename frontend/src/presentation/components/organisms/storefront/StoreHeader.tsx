import React, { useState } from 'react'

import { CalendarCheck } from 'lucide-react'

import { buildWaMeUrl } from '@shared/utils/whatsAppPhone'

import { colors2000s } from '../../../../theme/colors'
import type { resolveBrandTheme } from '../../../lib/brandTheme'

type BrandTheme = ReturnType<typeof resolveBrandTheme>

interface StoreHeaderProps {
  name: string
  logoUrl: string | null | undefined
  whatsappNumber: string | null | undefined
  misTurnosHref: string
  brand: BrandTheme
}

const LOGO_BOX = 'h-12 w-12 shrink-0 rounded-full sm:h-14 sm:w-14'

/**
 * Logo de la tienda; sin logo, o si la imagen no carga (la CSP de produccion
 * bloquea las URLs externas), la inicial del nombre en el color de marca.
 */
const StoreLogo: React.FC<{
  name: string
  logoUrl: string | null | undefined
  brand: BrandTheme
}> = ({ name, logoUrl, brand }) => {
  const [failed, setFailed] = useState(false)
  if (logoUrl && !failed) {
    return (
      <img
        src={logoUrl}
        alt={`Logo de ${name}`}
        width={56}
        height={56}
        decoding="async"
        onError={() => setFailed(true)}
        className={`${LOGO_BOX} border bg-white object-contain`}
        style={{ borderColor: colors2000s.border.default }}
      />
    )
  }
  const initial = Array.from(name.trim())[0]?.toLocaleUpperCase('es-AR') ?? ''
  return (
    <span
      aria-hidden="true"
      className={`${LOGO_BOX} flex items-center justify-center text-xl font-black`}
      style={{ background: brand.fill, color: brand.onFill }}
    >
      {initial}
    </span>
  )
}

/**
 * WhatsApp de la tienda: texto libre que carga el dueno. Si no se puede leer
 * como un numero confiable se muestra tal cual, sin link: un wa.me roto
 * mandaba la consulta a otro pais.
 */
const StoreWhatsAppContact: React.FC<{ phone: string; storeName: string; brand: BrandTheme }> = ({
  phone,
  storeName,
  brand
}) => {
  const href = buildWaMeUrl(phone, `Hola ${storeName}! Quiero consultar por un turno.`)
  if (!href) return <span className="break-all">{phone}</span>
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="inline-flex min-h-11 min-w-11 max-w-full items-center break-all rounded-sm py-2 underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-500"
      style={{ color: brand.ink }}
    >
      {phone}
    </a>
  )
}

/** Encabezado del portal publico (S1): una sola fila tambien en 360 px. */
export const StoreHeader: React.FC<StoreHeaderProps> = ({
  name,
  logoUrl,
  whatsappNumber,
  misTurnosHref,
  brand
}) => (
  <header className="mx-auto flex max-w-2xl items-center gap-2 sm:gap-3">
    {/* key: otro logo vuelve a intentar cargar aunque el anterior fallara. */}
    <StoreLogo key={logoUrl ?? ''} name={name} logoUrl={logoUrl} brand={brand} />
    <div className="min-w-0 flex-1">
      <h1
        title={name}
        className="truncate text-xl font-black tracking-tight sm:text-2xl"
        style={{ color: colors2000s.text.primary }}
      >
        {name}
      </h1>
      {whatsappNumber && (
        <div className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
          <StoreWhatsAppContact phone={whatsappNumber} storeName={name} brand={brand} />
        </div>
      )}
    </div>
    {/* Debajo de sm, solo el icono (el texto queda para lectores de pantalla):
        en 360 px la pastilla con texto le sacaba el lugar al nombre. */}
    <a
      href={misTurnosHref}
      className="flex min-h-11 min-w-11 shrink-0 items-center justify-center gap-2 rounded-xl border px-2 py-2.5 text-xs font-black uppercase tracking-widest sm:px-3 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-500"
      style={{
        background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
        borderColor: colors2000s.border.default,
        boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
        color: colors2000s.text.primary
      }}
    >
      <CalendarCheck
        aria-hidden="true"
        className="h-5 w-5 stroke-[2.5px] sm:h-3.5 sm:w-3.5"
        style={{ color: brand.ink }}
      />
      <span className="sr-only sm:not-sr-only">Mis turnos</span>
    </a>
  </header>
)
