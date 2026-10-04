import React from 'react'

import { colors2000s } from '../../../../theme/colors'
import type { SettingsFormData } from '../../../lib/settingsDraft'
import { numberInRange, SETTINGS_LIMITS } from '../../../lib/settingsValidation'
import { createSettingsInputStyle } from '../../../lib/surfaceStyles'

type PolicySettings = Pick<
  SettingsFormData,
  | 'cancellation_hours'
  | 'buffer_minutes'
  | 'min_booking_notice_hours'
  | 'deposit_far_notice_days'
  | 'deposit_far_notice_extra_percent'
  | 'deposit_new_client_extra_percent'
  | 'deposit_absent_client_extra_percent'
>

interface SettingsPoliciesTabProps {
  value: PolicySettings
  onChange: (patch: Partial<PolicySettings>) => void
}

/**
 * Pestana "Politicas" de Configuracion (F11b-08). Solo pinta: devuelve el
 * campo tocado, ya recortado a su tope, y la pagina lo suma al borrador.
 */
export const SettingsPoliciesTab: React.FC<SettingsPoliciesTabProps> = ({ value, onChange }) => (
  <div className="space-y-8">
    <div className="grid md:grid-cols-2 gap-8">
      <div className="space-y-3">
        <label
          className="block text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Cancelación (Horas)
        </label>
        <input
          type="number"
          min={SETTINGS_LIMITS.cancellation_hours.min}
          max={SETTINGS_LIMITS.cancellation_hours.max}
          value={value.cancellation_hours}
          onChange={(e) =>
            onChange({
              cancellation_hours: numberInRange(
                e.target.value,
                SETTINGS_LIMITS.cancellation_hours.min,
                SETTINGS_LIMITS.cancellation_hours.max
              )
            })
          }
          className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
          style={createSettingsInputStyle()}
          placeholder="24"
        />
        <p className="text-[10px] font-bold italic" style={{ color: colors2000s.text.secondary }}>
          Antelación mínima permitida para cancelar.
        </p>
      </div>
      <div className="space-y-3">
        <label
          className="block text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Buffer entre turnos (min)
        </label>
        <input
          type="number"
          min={SETTINGS_LIMITS.buffer_minutes.min}
          max={SETTINGS_LIMITS.buffer_minutes.max}
          value={value.buffer_minutes}
          onChange={(e) =>
            onChange({
              buffer_minutes: numberInRange(
                e.target.value,
                SETTINGS_LIMITS.buffer_minutes.min,
                SETTINGS_LIMITS.buffer_minutes.max
              )
            })
          }
          className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
          style={createSettingsInputStyle()}
          placeholder="0"
        />
        <p className="text-[10px] font-bold italic" style={{ color: colors2000s.text.secondary }}>
          Tiempo de limpieza/descanso automático.
        </p>
      </div>
      <div className="space-y-3">
        <label
          className="block text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Antelación mínima para reservar (horas)
        </label>
        <input
          type="number"
          min={0}
          max={168}
          value={value.min_booking_notice_hours}
          onChange={(e) =>
            onChange({
              min_booking_notice_hours: numberInRange(e.target.value, 0, 168)
            })
          }
          className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
          style={createSettingsInputStyle()}
          placeholder="2"
        />
        <p className="text-[10px] font-bold italic" style={{ color: colors2000s.text.secondary }}>
          Un cliente no puede reservar por la página con menos antelación que esta. Vos, desde el
          panel, sí.
        </p>
      </div>
    </div>

    <div
      className="rounded-3xl p-6 space-y-5"
      style={{
        background: 'white',
        border: `1px solid ${colors2000s.border.default}`,
        boxShadow: colors2000s.shadows.insetDark
      }}
    >
      <div>
        <h3
          className="text-sm font-black uppercase tracking-tight"
          style={{ color: colors2000s.text.primary }}
        >
          Seña según riesgo
        </h3>
        <p className="text-[10px] font-bold" style={{ color: colors2000s.text.secondary }}>
          Recargos que se suman a la seña del servicio, en puntos del precio. La seña nunca supera
          el precio y no aparece en servicios sin seña. 0 apaga la regla. El link que generás vos
          desde el panel sigue usando la seña base.
        </p>
      </div>
      <div className="grid md:grid-cols-2 gap-6">
        <DepositRuleInput
          label="Reservas con mucha antelación (días)"
          hint="A partir de cuántos días de antelación sube la seña."
          value={value.deposit_far_notice_days}
          max={365}
          onChange={(value) => onChange({ deposit_far_notice_days: value })}
        />
        <DepositRuleInput
          label="Recargo por antelación (%)"
          hint="Puntos que se suman cuando la reserva supera esos días."
          value={value.deposit_far_notice_extra_percent}
          max={100}
          onChange={(value) => onChange({ deposit_far_notice_extra_percent: value })}
        />
        <DepositRuleInput
          label="Recargo cliente nuevo (%)"
          hint="Para quien nunca tuvo un turno en tu negocio."
          value={value.deposit_new_client_extra_percent}
          max={100}
          onChange={(value) => onChange({ deposit_new_client_extra_percent: value })}
        />
        <DepositRuleInput
          label="Recargo por ausencias (%)"
          hint="Para quien ya faltó alguna vez sin avisar."
          value={value.deposit_absent_client_extra_percent}
          max={100}
          onChange={(value) => onChange({ deposit_absent_client_extra_percent: value })}
        />
      </div>
    </div>
  </div>
)

const DepositRuleInput: React.FC<{
  label: string
  hint: string
  value: number
  max: number
  onChange: (value: number) => void
}> = ({ label, hint, value, max, onChange }) => (
  <div className="space-y-2">
    <label
      className="block text-[10px] font-black uppercase tracking-widest"
      style={{ color: colors2000s.text.secondary }}
    >
      {label}
      <input
        type="number"
        min={0}
        max={max}
        value={value}
        onChange={(e) => onChange(numberInRange(e.target.value, 0, max))}
        className="mt-2 w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
        style={createSettingsInputStyle()}
      />
    </label>
    <p className="text-[10px] font-bold italic" style={{ color: colors2000s.text.secondary }}>
      {hint}
    </p>
  </div>
)
