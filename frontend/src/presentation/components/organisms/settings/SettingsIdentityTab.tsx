import React from 'react'

import { Loader2, Store } from 'lucide-react'

import type { BusinessType } from '@shared/types/business'

import { CustomClientFieldsEditor } from './CustomClientFieldsEditor'
import { buttonStyles2000s, colors2000s } from '../../../../theme/colors'
import { BUSINESS_TYPE_OPTIONS, type getBusinessLabels } from '../../../lib/businessLabels'
import type { SettingsFormData } from '../../../lib/settingsDraft'
import { normalizeSlugInput } from '../../../lib/settingsValidation'
import { createSettingsInputStyle } from '../../../lib/surfaceStyles'
import { ShareLinksPanel } from '../ShareLinksPanel'

type IdentitySettings = Pick<
  SettingsFormData,
  | 'business_type'
  | 'name'
  | 'slug'
  | 'logo_url'
  | 'primary_color'
  | 'cover_url'
  | 'whatsapp_number'
  | 'description'
  | 'custom_client_fields'
  | 'instagram_url'
  | 'facebook_url'
  | 'website_url'
>

interface SettingsIdentityTabProps {
  value: IdentitySettings
  labels: ReturnType<typeof getBusinessLabels>
  slugError: string | undefined
  logoError: string | null
  uploadingLogo: boolean
  onChange: (patch: Partial<IdentitySettings>) => void
  /** La validacion de la imagen (tipo y tamano, regla 19) vive en la pagina. */
  onLogoUpload: (event: React.ChangeEvent<HTMLInputElement>) => void
  /** Tienda suspendida: POST /stores/me/media responde 402 (FF-15). */
  readOnlyReason?: string | null
}

/**
 * Pestana "Identidad" de Configuracion (F11b-08). Solo pinta: subir el logo y
 * guardar los resuelve la pagina, que es quien tiene los hooks (D-58).
 */
export const SettingsIdentityTab: React.FC<SettingsIdentityTabProps> = ({
  value,
  labels,
  slugError,
  logoError,
  uploadingLogo,
  onChange,
  onLogoUpload,
  readOnlyReason = null
}) => (
  <div className="space-y-8">
    <div className="grid md:grid-cols-2 gap-8">
      <div className="space-y-3">
        <label
          className="block text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Rubro
        </label>
        <select
          value={value.business_type}
          onChange={(e) =>
            onChange({
              business_type: e.target.value as BusinessType
            })
          }
          className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
          style={createSettingsInputStyle()}
        >
          {BUSINESS_TYPE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
      <div className="space-y-3">
        <label
          className="block text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          {labels.businessNameLabel}
        </label>
        <input
          value={value.name}
          onChange={(e) => onChange({ name: e.target.value })}
          className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
          style={createSettingsInputStyle()}
          placeholder={labels.businessNamePlaceholder}
        />
      </div>
    </div>

    <div className="grid md:grid-cols-2 gap-8">
      <div className="space-y-3">
        <label
          className="block text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Slug de la URL
        </label>
        <div
          className="flex items-center gap-2 rounded-2xl px-5 py-3.5"
          style={createSettingsInputStyle()}
        >
          <span className="text-xs font-black opacity-30">/booking/</span>
          <input
            value={value.slug}
            onChange={(e) =>
              onChange({
                slug: normalizeSlugInput(e.target.value)
              })
            }
            className="flex-1 bg-transparent font-black outline-none"
            placeholder={labels.slugPlaceholder}
            aria-label="Slug de la URL"
            aria-invalid={slugError !== undefined}
          />
        </div>
        {slugError && (
          <p className="text-[10px] font-bold" style={{ color: colors2000s.status.danger.text }}>
            {slugError}
          </p>
        )}
        <ShareLinksPanel slug={value.slug} />
      </div>
      <div className="space-y-3">
        <label
          className="block text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Logo del negocio
        </label>
        <div className="flex items-center gap-4">
          <div
            className="w-20 h-20 rounded-md flex items-center justify-center overflow-hidden shrink-0"
            style={{
              background: 'white'
            }}
          >
            {value.logo_url ? (
              <img
                src={value.logo_url}
                alt="Logo"
                loading="lazy"
                decoding="async"
                width={80}
                height={80}
                className="w-full h-full object-contain"
              />
            ) : (
              <Store className="w-8 h-8" style={{ color: colors2000s.text.secondary }} />
            )}
          </div>
          <div className="flex-1 space-y-2">
            <label
              className={`inline-flex items-center gap-2 px-4 py-2.5 font-black uppercase tracking-widest text-[11px] transition-all active:scale-95 ${
                readOnlyReason ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'
              }`}
              style={buttonStyles2000s.default}
              title={readOnlyReason ?? undefined}
            >
              {uploadingLogo ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Store className="w-4 h-4" />
              )}
              {uploadingLogo ? 'Subiendo...' : 'Subir imagen'}
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="hidden"
                disabled={uploadingLogo || readOnlyReason !== null}
                onChange={onLogoUpload}
              />
            </label>
            <p className="text-[10px] font-bold" style={{ color: colors2000s.text.secondary }}>
              PNG, JPEG o WebP · máx 1 MB
            </p>
          </div>
        </div>
        {logoError && (
          <div
            role="alert"
            className="rounded-2xl px-4 py-2.5 text-xs font-bold"
            style={{
              background: colors2000s.status.danger.bg,
              color: colors2000s.status.danger.text
            }}
          >
            {logoError}
          </div>
        )}
        <input
          value={value.logo_url}
          onChange={(e) => onChange({ logo_url: e.target.value })}
          className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none text-xs"
          style={createSettingsInputStyle()}
          placeholder="…o pegá una URL https://"
        />
      </div>
      <div className="space-y-3">
        <label
          className="block text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Color de Marca
        </label>
        <div className="flex items-center gap-4">
          <input
            type="color"
            value={value.primary_color}
            onChange={(e) => onChange({ primary_color: e.target.value })}
            className="w-14 h-14 rounded-2xl bg-white border-none p-1 cursor-pointer shadow-inner"
            style={{ border: `1px solid ${colors2000s.border.default}` }}
          />
          <div
            className="flex-1 px-5 py-3.5 font-black uppercase tracking-widest rounded-2xl"
            style={createSettingsInputStyle()}
          >
            {value.primary_color}
          </div>
        </div>
      </div>
    </div>

    <div className="grid md:grid-cols-2 gap-8">
      <div className="space-y-3">
        <label
          className="block text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          URL de portada
        </label>
        <input
          value={value.cover_url}
          onChange={(e) => onChange({ cover_url: e.target.value })}
          className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
          style={createSettingsInputStyle()}
          placeholder="https://..."
        />
      </div>
      <div className="space-y-3">
        <label
          className="block text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          WhatsApp
        </label>
        <input
          value={value.whatsapp_number}
          onChange={(e) => onChange({ whatsapp_number: e.target.value })}
          className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
          style={createSettingsInputStyle()}
          placeholder="+54911..."
        />
      </div>
    </div>

    <div className="space-y-3">
      <label
        className="block text-[10px] font-black uppercase tracking-widest"
        style={{ color: colors2000s.text.secondary }}
      >
        Descripción pública
      </label>
      <textarea
        value={value.description}
        onChange={(e) => onChange({ description: e.target.value })}
        className="w-full min-h-28 rounded-2xl px-5 py-3.5 font-bold outline-none resize-y"
        style={createSettingsInputStyle()}
        placeholder="Breve descripción visible en el portal público."
      />
    </div>

    <CustomClientFieldsEditor
      fields={value.custom_client_fields}
      onChange={(custom_client_fields) => onChange({ custom_client_fields })}
    />

    <div className="grid md:grid-cols-3 gap-8">
      <div className="space-y-3">
        <label
          className="block text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Instagram
        </label>
        <input
          value={value.instagram_url}
          onChange={(e) => onChange({ instagram_url: e.target.value })}
          className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
          style={createSettingsInputStyle()}
          placeholder="https://instagram.com/..."
        />
      </div>
      <div className="space-y-3">
        <label
          className="block text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Facebook
        </label>
        <input
          value={value.facebook_url}
          onChange={(e) => onChange({ facebook_url: e.target.value })}
          className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
          style={createSettingsInputStyle()}
          placeholder="https://facebook.com/..."
        />
      </div>
      <div className="space-y-3">
        <label
          className="block text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Sitio web
        </label>
        <input
          value={value.website_url}
          onChange={(e) => onChange({ website_url: e.target.value })}
          className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
          style={createSettingsInputStyle()}
          placeholder="https://..."
        />
      </div>
    </div>
  </div>
)
