import React from 'react'

import { colors2000s } from '../../../../theme/colors'
import type { SettingsFormData } from '../../../lib/settingsDraft'
import { ToggleSwitch } from '../../molecules/ToggleSwitch'

type NotificationSettings = Pick<
  SettingsFormData,
  'send_email_confirmation' | 'send_email_reminders'
>

interface SettingsNotificationsTabProps {
  value: NotificationSettings
  onChange: (patch: Partial<NotificationSettings>) => void
}

/**
 * Pestana "Notificaciones" de Configuracion (F11b-08). Solo pinta: devuelve el
 * campo tocado y la pagina lo suma al borrador.
 */
export const SettingsNotificationsTab: React.FC<SettingsNotificationsTabProps> = ({
  value,
  onChange
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
  </div>
)
