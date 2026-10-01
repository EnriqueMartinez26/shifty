import { create2000sPanelStyle } from './surfaceStyles'
import { colors2000s } from '../../theme/colors'

// Superficies de la agenda que comparten CalendarContainer y sus organismos
// (F11c-08): salieron tal cual del contenedor.

export const panelStyle = create2000sPanelStyle()

export const canvasStyle = {
  background: 'white',
  border: `1px solid ${colors2000s.border.default}`,
  boxShadow: colors2000s.shadows.outerMedium
}

export const cardStyle = {
  background: 'white',
  border: `1px solid ${colors2000s.border.light}`,
  boxShadow: colors2000s.shadows.insetDark
}

export const fieldStyle = {
  ...cardStyle,
  color: colors2000s.text.primary
}
