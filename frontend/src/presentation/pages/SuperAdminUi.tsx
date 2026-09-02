import React from 'react'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { create2000sInnerCardStyle, create2000sInputStyle } from '../lib/surfaceStyles'

/**
 * Primitivos de UI del panel SuperAdmin (inputs, toggles, botones).
 *
 * Vivían como funciones sueltas dentro de SuperAdmin.tsx, que ya era un
 * componente gigante. Son presentacionales puros (props → JSX, sin estado ni
 * hooks), así que salen a este módulo para achicar la página y poder reusarlos.
 */

const primaryActionStyle = {
  ...buttonStyles2000s.selected,
  borderRadius: '14px',
  padding: '12px 16px',
  fontSize: '10px',
  fontWeight: 900,
  letterSpacing: '0.12em',
  textTransform: 'uppercase' as const
}

const secondaryActionStyle = {
  ...buttonStyles2000s.default,
  borderRadius: '14px',
  padding: '12px 16px',
  fontSize: '10px',
  fontWeight: 900,
  letterSpacing: '0.12em',
  textTransform: 'uppercase' as const
}

const dangerActionStyle = {
  ...buttonStyles2000s.default,
  borderRadius: '14px',
  padding: '12px 16px',
  fontSize: '10px',
  fontWeight: 900,
  letterSpacing: '0.12em',
  textTransform: 'uppercase' as const,
  color: '#b91c1c',
  background: 'rgba(239,68,68,0.06)'
}

export const FieldLabel: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <label
    className="mb-1 block text-[10px] font-black uppercase tracking-widest"
    style={{ color: colors2000s.text.secondary }}
  >
    {children}
  </label>
)

export const TextInput: React.FC<React.InputHTMLAttributes<HTMLInputElement>> = ({
  className = '',
  ...props
}) => (
  <input
    {...props}
    className={`w-full rounded-2xl px-4 py-3 text-sm font-bold ${className}`.trim()}
    style={create2000sInputStyle()}
  />
)

export const TextArea: React.FC<React.TextareaHTMLAttributes<HTMLTextAreaElement>> = ({
  className = '',
  ...props
}) => (
  <textarea
    {...props}
    className={`min-h-24 w-full rounded-2xl px-4 py-3 text-sm font-bold resize-y ${className}`.trim()}
    style={create2000sInputStyle()}
  />
)

export const SelectInput: React.FC<React.SelectHTMLAttributes<HTMLSelectElement>> = ({
  className = '',
  children,
  ...props
}) => (
  <select
    {...props}
    className={`w-full rounded-2xl px-4 py-3 text-sm font-bold ${className}`.trim()}
    style={create2000sInputStyle()}
  >
    {children}
  </select>
)

export const ToggleRow: React.FC<{
  label: string
  description: string
  checked: boolean
  onToggle: () => void
}> = ({ label, description, checked, onToggle }) => (
  <div
    className="flex items-center justify-between gap-4 rounded-2xl px-4 py-3"
    style={create2000sInnerCardStyle()}
  >
    <div>
      <p
        className="text-[10px] font-black uppercase tracking-widest"
        style={{ color: colors2000s.text.secondary }}
      >
        {label}
      </p>
      <p className="mt-1 text-xs font-bold" style={{ color: colors2000s.text.primary }}>
        {description}
      </p>
    </div>
    <button
      type="button"
      onClick={onToggle}
      className="relative h-7 w-14 rounded-full"
      style={{
        background: checked ? colors2000s.orange.light : colors2000s.bg.disabled,
        border: `1px solid ${colors2000s.border.default}`,
        boxShadow: colors2000s.shadows.insetDark
      }}
    >
      <span
        className="absolute top-1 h-5 w-5 rounded-full transition-all"
        style={{
          left: checked ? '32px' : '4px',
          background: 'white',
          boxShadow: '0 2px 4px rgba(0,0,0,0.2)'
        }}
      />
    </button>
  </div>
)

export const ActionButton: React.FC<{
  label: string
  onClick: () => void
  disabled?: boolean
  tone?: 'primary' | 'secondary' | 'danger'
}> = ({ label, onClick, disabled = false, tone = 'secondary' }) => {
  const style =
    tone === 'primary'
      ? primaryActionStyle
      : tone === 'danger'
        ? dangerActionStyle
        : secondaryActionStyle
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="disabled:opacity-50"
      style={style}
    >
      {label}
    </button>
  )
}

export const MiniButton: React.FC<{
  label: string
  onClick: (event: React.MouseEvent<HTMLButtonElement>) => void
  tone?: 'default' | 'primary' | 'danger'
  disabled?: boolean
}> = ({ label, onClick, tone = 'default', disabled = false }) => {
  const style =
    tone === 'primary'
      ? primaryActionStyle
      : tone === 'danger'
        ? dangerActionStyle
        : secondaryActionStyle
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="px-3 py-2 text-[10px] font-black uppercase tracking-widest disabled:opacity-50"
      style={{ ...style, padding: '8px 12px' }}
    >
      {label}
    </button>
  )
}
