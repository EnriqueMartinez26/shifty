import type { CSSProperties } from 'react'

import { colors2000s } from '../../theme/colors'

export const create2000sPanelStyle = (): CSSProperties => ({
  background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
  border: `1px solid ${colors2000s.border.default}`,
  boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`
})

export const create2000sInputStyle = (): CSSProperties => ({
  background: 'white',
  border: `1px solid ${colors2000s.border.default}`,
  boxShadow: colors2000s.shadows.insetDark,
  color: colors2000s.text.primary
})

export const create2000sInnerCardStyle = (): CSSProperties => ({
  background: 'white',
  border: `1px solid ${colors2000s.border.light}`,
  boxShadow: colors2000s.shadows.outer
})

export const create2000sEmptyStateStyle = (): CSSProperties => ({
  background: 'white',
  border: `1px dashed ${colors2000s.border.default}`,
  boxShadow: colors2000s.shadows.insetDark
})

export const create2000sListCardStyle = (
  background: string = 'white',
  borderColor: string = colors2000s.border.light
): CSSProperties => ({
  background,
  border: `1px solid ${borderColor}`,
  boxShadow: colors2000s.shadows.insetDark
})

export const createBookingBackButtonStyle = (): CSSProperties => ({
  background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
  borderColor: colors2000s.orange.accent,
  boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`,
  color: '#ffffff'
})

export const createBookingInputStyle = (): CSSProperties => ({
  background: '#ffffff',
  border: `1px solid ${colors2000s.border.default}`,
  boxShadow: colors2000s.shadows.insetDark,
  color: colors2000s.text.primary
})

export const createBookingSurfaceStyle = (): CSSProperties => ({
  background: '#ffffff',
  border: `1px solid ${colors2000s.border.light}`,
  boxShadow: colors2000s.shadows.insetDark
})

export const createBookingAccentBoxStyle = (
  background: string,
  borderColor: string,
  color: string = colors2000s.text.primary
): CSSProperties => ({
  background,
  border: `1px solid ${borderColor}`,
  boxShadow: colors2000s.shadows.insetDark,
  color
})

export const createBookingChoiceCardStyle = (isSelected: boolean): CSSProperties => ({
  background: isSelected
    ? `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`
    : `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
  borderColor: isSelected ? colors2000s.orange.accent : colors2000s.border.default,
  boxShadow: isSelected
    ? `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`
    : `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
})

export const create2000sModalSurfaceStyle = (): CSSProperties => ({
  background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
  border: `1px solid ${colors2000s.border.default}`,
  boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`
})

export const create2000sModalInputStyle = (): CSSProperties => ({
  background: 'white',
  border: `1px solid ${colors2000s.border.default}`,
  boxShadow: colors2000s.shadows.insetDark,
  color: colors2000s.text.primary,
  outline: 'none'
})

export const createDashboardPanelStyle = (): CSSProperties => ({
  background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
  border: `1px solid ${colors2000s.border.default}`,
  borderRadius: 24,
  boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`,
  minWidth: 0,
  overflow: 'hidden'
})

export const createDashboardListItemStyle = (
  borderColor: string,
  background: string,
  padding = 16
): CSSProperties => ({
  padding,
  borderRadius: 18,
  background,
  border: `1px solid ${borderColor}`,
  boxShadow: colors2000s.shadows.insetLight
})

export const createSettingsInputStyle = (): CSSProperties => ({
  background: 'white',
  border: `1px solid ${colors2000s.border.default}`,
  boxShadow: colors2000s.shadows.insetDark,
  color: colors2000s.text.primary
})

export const createSettingsCardStyle = (
  background: string = 'white',
  borderColor: string = colors2000s.border.light,
  shadow: string = colors2000s.shadows.outer
): CSSProperties => ({
  background,
  border: `1px solid ${borderColor}`,
  boxShadow: shadow
})
