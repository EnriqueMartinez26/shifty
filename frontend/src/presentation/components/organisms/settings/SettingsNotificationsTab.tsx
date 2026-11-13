import React, { useId } from 'react'

import { colors2000s } from '../../../../theme/colors'
import type { SettingsFormData } from '../../../lib/settingsDraft'
import { createSettingsInputStyle } from '../../../lib/surfaceStyles'
import { ToggleSwitch } from '../../molecules/ToggleSwitch'

type NotificationSettings = Pick<
  SettingsFormData,
  'send_email_confirmation' | 'send_email_reminders' | 'contact_email'
>

interface SettingsNotificationsTabProps {
  value: NotificationSettings
  onChange: (patch: Partial<NotificationSettings>) => void
  /** Mensaje de `validateSettingsDraft`; sin error no se muestra nada. */
  contactEmailError?: string
}

interface ContactEmailFieldProps {
  value: string
  onChange: (contactEmail: string) => void
  error?: string
}

/** Reply-To de los mails a los clientes (#283). Vacio: sin mail de contacto. */
const ContactEmailField: React.FC<ContactEmailFieldProps> = ({ value, onChange, error }) => {
  const inputId = useId()
  const helpId = useId()
  return (
    <div className="space-y-3">
      <label
        htmlFor={inputId}
        className="block text-[10px] font-black uppercase tracking-widest"
        style={{ color: colors2000s.text.secondary }}
      >
        Mail de contacto
      </label>
      <input
        id={inputId}
        type="email"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
        style={createSettingsInputStyle()}
        placeholder="hola@tunegocio.com"
        autoComplete="email"
        aria-describedby={helpId}
        aria-invalid={error !== undefined}
      />
      <p
        id={helpId}
        className="text-[10px] font-bold"
        style={{ color: colors2000s.text.secondary }}
      >
        Las respuestas de tus clientas a los mails de Shifty llegan acá.
      </p>
      {error && (
        <p
          role="alert"
          className="text-[10px] font-bold"
          style={{ color: colors2000s.status.danger.text }}
        >
          {error}
        </p>
      )}
    </div>
  )
}

/**
 * Pestana "Notificaciones" de Configuracion (F11b-08). Solo pinta: devuelve el
 * campo tocado y la pagina lo suma al borrador.
 */
export const SettingsNotificationsTab: React.FC<SettingsNotificationsTabProps> = ({
  value,
  onChange,
  contactEmailError
}) => (
  <div className="space-y-6">
    <div
      className="flex items-center justify-between p-6 rounded-md transition-all"
      style={{
        background: 'white',
        border: `1px solid ${colors2000s.border.light}`,
        boxShadow: colors2000s.shadows.outer
      }}
    >
      <div className="space-y-1">
        <p
          className="font-black uppercase tracking-tight"
          style={{ color: colors2000s.text.primary }}
        >
          Email de Confirmación
        </p>
        <p
          className="text-[10px] font-bold uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Enviar al confirmar reserva.
        </p>
      </div>
      <ToggleSwitch
        label="Email de Confirmación"
        checked={value.send_email_confirmation}
        onToggle={() => onChange({ send_email_confirmation: !value.send_email_confirmation })}
      />
    </div>

    <div
      className="flex items-center justify-between p-6 rounded-md transition-all"
      style={{
        background: 'white',
        border: `1px solid ${colors2000s.border.light}`,
        boxShadow: colors2000s.shadows.outer
      }}
    >
      <div className="space-y-1">
        <p
          className="font-black uppercase tracking-tight"
          style={{ color: colors2000s.text.primary }}
        >
          Recordatorios 24hs
        </p>
        <p
          className="text-[10px] font-bold uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Aviso automático un día antes.
        </p>
      </div>
      <ToggleSwitch
        label="Recordatorios 24hs"
        checked={value.send_email_reminders}
        onToggle={() => onChange({ send_email_reminders: !value.send_email_reminders })}
      />
    </div>

    <ContactEmailField
      value={value.contact_email}
      onChange={(contact_email) => onChange({ contact_email })}
      error={contactEmailError}
    />
  </div>
)
