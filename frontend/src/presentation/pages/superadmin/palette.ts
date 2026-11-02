import { colors2000s } from '../../../theme/colors'

/** Paleta de marca local al panel global; no altera los temas de las tiendas. */
export const superAdminPalette = {
  orangeLight: colors2000s.orange.light,
  orangeDark: colors2000s.orange.dark,
  orangePale: '#fff7ed',
  onOrange: colors2000s.text.onOrange,
  brandGradient: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
  brandShadow: '0 2px 4px rgba(230, 126, 34, 0.22)',
  icon: colors2000s.orange.dark
} as const

export const superAdminPrimaryControlStyle = {
  background: superAdminPalette.brandGradient,
  border: `1px solid ${superAdminPalette.orangeDark}`,
  color: superAdminPalette.onOrange,
  boxShadow: `inset 0 1px 0 rgba(255, 255, 255, 0.24), ${superAdminPalette.brandShadow}`
}

export const superAdminSelectedControlStyle = {
  ...superAdminPrimaryControlStyle,
  borderRadius: '12px'
}

export const superAdminGlobalScopeStyle = {
  background: superAdminPalette.brandGradient,
  border: `1px solid ${superAdminPalette.orangeDark}`,
  color: superAdminPalette.onOrange
}

export const superAdminTenantScopeStyle = {
  background: superAdminPalette.orangePale,
  border: `1px solid ${superAdminPalette.orangeLight}`,
  color: colors2000s.text.primary
}
