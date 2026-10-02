import React from 'react'

import type { StoreFeatureFlags } from '@application/services/StoreSettingsService'

import { colors2000s } from '../../../../theme/colors'
import { ToggleSwitch } from '../../molecules/ToggleSwitch'

// Solo los flags que el backend lee para decidir algo (FF-28).
// `advanced_reports` y `new_calendar` siguen en el contrato (`StoreFeatureFlags`,
// `DEFAULT_FEATURE_FLAGS`) pero ningun camino los consulta: mostrarlos era
// ofrecer interruptores que no hacen nada. `planSave` solo manda las claves
// que cambiaron, asi que ocultarlos no los pisa en la base.
const FEATURE_LABELS = [
  {
    key: 'payments',
    title: 'Cobros online y señas',
    description: 'Mercado Pago, confirmación manual, devoluciones y actualización de pagos.'
  },
  {
    key: 'ledger',
    title: 'Deuda / fiado',
    description: 'Cuenta pendiente por cliente con cargos, pagos, ajustes y devoluciones.'
  },
  {
    key: 'otp_booking',
    title: 'Código por email en la reserva pública',
    description: 'Pide un código de verificación, enviado por email, antes de confirmar la reserva.'
  }
] as const

interface SettingsFeaturesTabProps {
  flags: StoreFeatureFlags
  onChange: (flags: StoreFeatureFlags) => void
  /** Tienda suspendida: PUT /stores/me/feature-flags responde 402 (FF-15). */
  readOnlyReason?: string | null
}

/**
 * Pestana "Funciones" de Configuracion (F11b-08). Solo pinta: devuelve los
 * flags con el interruptor tocado y la pagina los suma al borrador.
 */
export const SettingsFeaturesTab: React.FC<SettingsFeaturesTabProps> = ({
  flags,
  onChange,
  readOnlyReason = null
}) => (
  <div className="space-y-6">
    <h3
      className="text-lg font-black uppercase tracking-tight"
      style={{ color: colors2000s.orange.accent }}
    >
      Funciones de la tienda
    </h3>
    {FEATURE_LABELS.map((feature) => {
      const enabled = Boolean(flags?.[feature.key])
      return (
        <div
          key={feature.key}
          className="flex items-center justify-between gap-6 p-6 rounded-md transition-all"
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
              {feature.title}
            </p>
            <p
              className="text-[10px] font-bold uppercase tracking-widest"
              style={{ color: colors2000s.text.secondary }}
            >
              {feature.description}
            </p>
          </div>
          <ToggleSwitch
            label={feature.title}
            checked={enabled}
            disabled={readOnlyReason !== null}
            title={readOnlyReason ?? undefined}
            onToggle={() => onChange({ ...flags, [feature.key]: !enabled })}
          />
        </div>
      )
    })}
  </div>
)
