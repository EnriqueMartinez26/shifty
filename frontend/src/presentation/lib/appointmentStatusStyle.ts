import { colors2000s } from '../../theme/colors'

interface StatusStyle {
  accent: string
  background: string
  text: string
}

/** Colores de una tarjeta de turno segun su estado (agenda: dia, semana, mes, lista). */
export const statusStyle = (status: string): StatusStyle => {
  if (status === 'absent') {
    const color = colors2000s.status.danger
    return {
      accent: color.accent,
      background: `linear-gradient(180deg, ${color.bg} 0%, ${color.border} 100%)`,
      text: color.text
    }
  }
  if (status === 'pending_payment') {
    const color = colors2000s.status.warning
    return {
      accent: color.accent,
      background: `linear-gradient(180deg, ${color.bg} 0%, ${color.border} 100%)`,
      text: color.text
    }
  }
  if (status === 'confirmed') {
    const color = colors2000s.status.info
    return {
      accent: color.accent,
      background: `linear-gradient(180deg, ${color.bg} 0%, ${color.border} 100%)`,
      text: color.text
    }
  }
  if (status === 'completed') {
    const color = colors2000s.status.success
    return {
      accent: color.accent,
      background: `linear-gradient(180deg, ${color.bg} 0%, ${color.border} 100%)`,
      text: color.text
    }
  }
  return {
    accent: colors2000s.orange.accent,
    background: 'linear-gradient(180deg, #ffffff 0%, #f6f8f9 100%)',
    text: colors2000s.text.primary
  }
}
