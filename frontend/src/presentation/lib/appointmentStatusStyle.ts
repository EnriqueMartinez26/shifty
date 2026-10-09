import { colors2000s } from '../../theme/colors'

interface StatusStyle {
  accent: string
  background: string
  text: string
}

/** Colores de una tarjeta de turno segun su estado (agenda: dia, semana, mes, lista). */
export const statusStyle = (status: string): StatusStyle => {
  if (status === 'absent') {
    return {
      accent: '#b91c1c',
      background: 'linear-gradient(180deg, #fef2f2 0%, #fecaca 100%)',
      text: '#7f1d1d'
    }
  }
  if (status === 'pending_payment') {
    return {
      accent: '#d97706',
      background: 'linear-gradient(180deg, #fff7ed 0%, #fed7aa 100%)',
      text: '#9a3412'
    }
  }
  if (status === 'confirmed') {
    return {
      accent: '#2563eb',
      background: 'linear-gradient(180deg, #eff6ff 0%, #dbeafe 100%)',
      text: '#1d4ed8'
    }
  }
  if (status === 'completed') {
    return {
      accent: '#15803d',
      background: 'linear-gradient(180deg, #ecfdf5 0%, #dcfce7 100%)',
      text: '#166534'
    }
  }
  return {
    accent: colors2000s.orange.accent,
    background: 'linear-gradient(180deg, #ffffff 0%, #f6f8f9 100%)',
    text: colors2000s.text.primary
  }
}
