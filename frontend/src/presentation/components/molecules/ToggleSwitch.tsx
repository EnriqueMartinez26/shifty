import React from 'react'

import { colors2000s } from '../../../theme/colors'

interface ToggleSwitchProps {
  checked: boolean
  onToggle: () => void
  /** Nombre accesible: el interruptor no tiene texto visible propio. */
  label: string
}

/**
 * Interruptor on/off del panel. Estaba escrito a mano en `ToggleRow`, tres
 * veces en Settings y una en Promociones; cada fila conserva su propio
 * envoltorio y solo comparte esta pieza.
 */
export const ToggleSwitch: React.FC<ToggleSwitchProps> = ({ checked, onToggle, label }) => (
  <button
    type="button"
    role="switch"
    aria-checked={checked}
    aria-label={label}
    onClick={onToggle}
    className="relative h-7 w-14 flex-shrink-0 rounded-full transition-all"
    style={{
      background: checked ? colors2000s.orange.light : colors2000s.bg.disabled,
      // El riel solo no se distingue de la tarjeta blanca: apagado, gris claro
      // (1.23:1); prendido, el naranja de marca (2.31:1). Un anillo interior le
      // da borde sin mover la perilla (una sombra no ocupa lugar como un
      // border): gris 4.29:1 apagado, naranja acento 4.26:1 prendido.
      boxShadow: `${colors2000s.shadows.insetDark}, inset 0 0 0 1px ${
        checked ? colors2000s.orange.accent : colors2000s.text.secondary
      }`
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
)
