import React from 'react'

import { Loader2 } from 'lucide-react'

import { buttonStyles2000s, colors2000s } from '../../../../theme/colors'
import { createSettingsInputStyle } from '../../../lib/surfaceStyles'

interface PasswordForm {
  current: string
  new: string
  confirm: string
}

interface SettingsSecurityTabProps {
  /** Lo tipeado vive en la pagina: sobrevive a cambiar de pestana. */
  form: PasswordForm
  onFormChange: (form: PasswordForm) => void
  onSubmit: (event: React.FormEvent) => void
  saving: boolean
}

/**
 * Pestana "Seguridad" de Configuracion (F11b-08). Solo pinta: validar y
 * cambiar la clave lo resuelve la pagina, que escribe el cartel de error
 * compartido.
 */
export const SettingsSecurityTab: React.FC<SettingsSecurityTabProps> = ({
  form,
  onFormChange,
  onSubmit,
  saving
}) => (
  <form onSubmit={onSubmit} className="max-w-md space-y-6">
    <h3
      className="text-lg font-black uppercase tracking-tight"
      style={{ color: colors2000s.orange.accent }}
    >
      Seguridad
    </h3>
    <div className="space-y-4">
      <div className="space-y-2">
        <label
          className="text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Contraseña Actual
        </label>
        <input
          type="password"
          required
          value={form.current}
          onChange={(e) => onFormChange({ ...form, current: e.target.value })}
          className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
          style={createSettingsInputStyle()}
        />
      </div>

      <div className="space-y-2">
        <label
          className="text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Nueva Contraseña
        </label>
        <input
          type="password"
          required
          value={form.new}
          onChange={(e) => onFormChange({ ...form, new: e.target.value })}
          className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
          style={createSettingsInputStyle()}
        />
      </div>

      <div className="space-y-2">
        <label
          className="text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Confirmar Nueva
        </label>
        <input
          type="password"
          required
          value={form.confirm}
          onChange={(e) => onFormChange({ ...form, confirm: e.target.value })}
          className="w-full rounded-2xl px-5 py-3.5 font-bold outline-none"
          style={createSettingsInputStyle()}
        />
      </div>
    </div>

    <button
      type="submit"
      disabled={saving}
      className="w-full py-4 rounded-2xl font-black uppercase tracking-widest text-sm transition-all active:scale-[0.98] disabled:opacity-50"
      style={buttonStyles2000s.selected}
    >
      {saving ? <Loader2 className="w-5 h-5 animate-spin mx-auto" /> : 'Actualizar Acceso'}
    </button>
  </form>
)
