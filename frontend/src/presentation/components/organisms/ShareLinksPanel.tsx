import React, { useState } from 'react'

import { Check, Copy, Share2 } from 'lucide-react'

import { useServicesCatalog } from '@presentation/hooks/useServicesCatalog'

import { colors2000s } from '../../../theme/colors'

interface ShareLinksPanelProps {
  slug: string
}

export interface ShareLink {
  label: string
  url: string
}

/** Link general de la tienda mas uno por servicio (deep-link de la Fase 3). */
export const buildShareLinks = (
  origin: string,
  slug: string,
  services: ReadonlyArray<{ public_id: string; name: string }>
): ShareLink[] => {
  if (!slug) return []
  const base = `${origin.replace(/\/$/, '')}/b/${slug}`
  return [
    { label: 'Reservar (todos los servicios)', url: base },
    ...services.map((service) => ({
      label: service.name,
      url: `${base}?service=${encodeURIComponent(service.public_id)}`
    })),
    { label: 'Mis turnos (para tus clientes)', url: `${base}/mis-turnos` }
  ]
}

/**
 * Links listos para mandar a mano por WhatsApp o pegar en Instagram. Es el
 * canal real de una tienda chica: no hay integracion que los publique sola.
 */
export const ShareLinksPanel: React.FC<ShareLinksPanelProps> = ({ slug }) => {
  const { data: services } = useServicesCatalog()
  const [copiado, setCopiado] = useState<string | null>(null)
  const links = buildShareLinks(
    typeof window === 'undefined' ? '' : window.location.origin,
    slug,
    (services ?? []).map((service) => ({ public_id: service.id, name: service.name }))
  )

  if (links.length === 0) return null

  const copiar = async (url: string) => {
    try {
      await window.navigator.clipboard.writeText(url)
      setCopiado(url)
    } catch {
      // Sin permiso de portapapeles: el link queda visible para copiarlo a mano.
      setCopiado(null)
    }
  }

  return (
    <div
      className="rounded-3xl p-6 space-y-4"
      style={{
        background: 'white',
        border: `1px solid ${colors2000s.border.default}`,
        boxShadow: colors2000s.shadows.insetDark
      }}
    >
      <div className="flex items-center gap-2">
        <Share2 className="w-4 h-4 text-orange-500" />
        <h3
          className="text-sm font-black uppercase tracking-tight"
          style={{ color: colors2000s.text.primary }}
        >
          Links para compartir
        </h3>
      </div>
      <p className="text-[10px] font-bold" style={{ color: colors2000s.text.secondary }}>
        Mandalos por WhatsApp o ponelos en tu perfil de Instagram. El link de un servicio abre la
        reserva con ese servicio ya elegido.
      </p>
      <ul className="space-y-2">
        {links.map((link) => (
          <li
            key={link.url}
            className="flex items-center gap-2 rounded-xl px-3 py-2"
            style={{ border: `1px solid ${colors2000s.border.light}` }}
          >
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-black uppercase tracking-widest truncate">
                {link.label}
              </p>
              <p className="text-[10px] font-bold text-gray-500 truncate">{link.url}</p>
            </div>
            <button
              type="button"
              onClick={() => {
                void copiar(link.url)
              }}
              aria-label={`Copiar link de ${link.label}`}
              className="rounded-lg px-3 py-2 text-[9px] font-black uppercase tracking-widest inline-flex items-center gap-1"
              style={{ border: `1px solid ${colors2000s.border.default}` }}
            >
              {copiado === link.url ? (
                <>
                  <Check className="w-3 h-3 text-emerald-600" /> Copiado
                </>
              ) : (
                <>
                  <Copy className="w-3 h-3" /> Copiar
                </>
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
