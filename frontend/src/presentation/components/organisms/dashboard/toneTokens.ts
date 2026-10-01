import type { Tone } from './types'
import { colors2000s } from '../../../../theme/colors'

export const toneTokens = (tone: Tone = 'neutral') => {
  if (tone === 'primary') {
    return {
      border: colors2000s.orange.accent,
      accent: colors2000s.orange.accent,
      background: 'rgba(255, 140, 66, 0.12)'
    }
  }
  if (tone === 'success') {
    return {
      border: 'rgba(16, 185, 129, 0.45)',
      accent: '#0f9f6e',
      background: 'rgba(16, 185, 129, 0.1)'
    }
  }
  if (tone === 'warning') {
    return {
      border: 'rgba(245, 158, 11, 0.42)',
      accent: '#b76a00',
      background: 'rgba(245, 158, 11, 0.12)'
    }
  }
  if (tone === 'danger') {
    return {
      border: 'rgba(239, 68, 68, 0.38)',
      accent: '#d13b3b',
      background: 'rgba(239, 68, 68, 0.1)'
    }
  }
  return {
    border: colors2000s.border.light,
    accent: colors2000s.text.secondary,
    background: 'rgba(255, 255, 255, 0.45)'
  }
}
