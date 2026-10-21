import React, { useState } from 'react'

import { CalendarCheck, MessageCircle } from 'lucide-react'

import { buildWaMeUrl } from '@shared/utils/whatsAppPhone'

import { StoreCover } from './StoreCover'
import { colors2000s } from '../../../../theme/colors'
import type { resolveBrandTheme } from '../../../lib/brandTheme'
import { createBookingBackButtonStyle } from '../../../lib/surfaceStyles'

type BrandTheme = ReturnType<typeof resolveBrandTheme>

interface StoreHeaderProps {
  name: string
  logoUrl: string | null | undefined
  coverUrl: string | null | undefined
  whatsappNumber: string | null | undefined
  misTurnosHref: string
  brand: BrandTheme
}

// Logo redondo con aro blanco que pisa el borde inferior de la portada por la
// mitad de su alto (76 px en el celular, 112 px en la compu).
const LOGO_BOX =
  'h-[76px] w-[76px] -mt-[38px] shrink-0 rounded-full border-4 border-white sm:h-28 sm:w-28 sm:-mt-14'
const LOGO_SHADOW = { boxShadow: colors2000s.shadows.outer }
const FOCUS_RING =
  'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-orange-500'

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
        width={112}
        height={112}
        decoding="async"
        onError={() => setFailed(true)}
        className={`${LOGO_BOX} bg-white object-contain`}
        style={LOGO_SHADOW}
      />
    )
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

/**
 * WhatsApp de la tienda: texto libre que carga el dueno. Si no se puede leer
 * como un numero confiable se muestra tal cual, sin link: un wa.me roto
 * mandaba la consulta a otro pais. Texto neutro (S9), nunca un tono de marca.
 */
const StoreWhatsAppContact: React.FC<{ phone: string; storeName: string }> = ({
  phone,
  storeName
}) => {
  const icon = <MessageCircle aria-hidden="true" className="h-4 w-4 shrink-0 stroke-[2.5px]" />
  const href = buildWaMeUrl(phone, `Hola ${storeName}! Quiero consultar por un turno.`)
  if (!href) {
    return (
      <span className="inline-flex max-w-full items-center gap-1.5 break-all py-2">
        {icon}
        <span>{phone}</span>
      </span>
    )
  }
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={`inline-flex min-h-11 min-w-11 max-w-full items-center gap-1.5 break-all rounded-sm py-2 underline underline-offset-2 ${FOCUS_RING}`}
      style={{ color: colors2000s.text.primary }}
    >
      {icon}
      <span>{phone}</span>
    </a>
  )
}

/**
 * Encabezado del portal publico (S1, S9): la portada arriba, el logo redondo
 * pisandola y, al lado, el nombre de la tienda, su WhatsApp y "Mis turnos".
 */
export const StoreHeader: React.FC<StoreHeaderProps> = ({
  name,
  logoUrl,
  coverUrl,
  whatsappNumber,
  misTurnosHref,
  brand
}) => (
  <header className="mx-auto w-full max-w-2xl">
    <StoreCover coverUrl={coverUrl} brand={brand} />
    {/* En la compu, el mismo margen interno que la tarjeta del wizard: el logo
        no queda sobre la esquina redondeada de la portada. */}
    <div className="flex items-start gap-3 px-4 sm:gap-4 sm:px-8">
      {/* key: otro logo vuelve a intentar cargar aunque el anterior fallara. */}
      <StoreLogo key={logoUrl ?? ''} name={name} logoUrl={logoUrl} brand={brand} />
      <div className="min-w-0 flex-1 pt-2 sm:pt-3">
        <h1
          title={name}
          className="line-clamp-2 break-words text-xl font-black tracking-tight sm:text-2xl"
          style={{ color: colors2000s.text.primary }}
        >
          {name}
        </h1>
        {whatsappNumber && (
          <div className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            <StoreWhatsAppContact phone={whatsappNumber} storeName={name} />
          </div>
        )}
      </div>
      {/* Debajo de sm, solo el icono (el texto queda para lectores de pantalla):
          en 360 px la pastilla con texto le sacaba el lugar al nombre. */}
      <a
        href={misTurnosHref}
        className={`mt-2 flex min-h-11 min-w-11 shrink-0 items-center justify-center gap-2 rounded-xl border px-2 py-2.5 text-xs font-black uppercase tracking-widest sm:mt-3 sm:px-3 ${FOCUS_RING}`}
        style={createBookingBackButtonStyle()}
      >
        <CalendarCheck aria-hidden="true" className="h-5 w-5 stroke-[2.5px] sm:h-3.5 sm:w-3.5" />
        <span className="sr-only sm:not-sr-only">Mis turnos</span>
      </a>
    </div>
  </header>
)
