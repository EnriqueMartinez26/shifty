import type React from 'react'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'

/**
 * Store brand color used by the booking flow, cover, and logo fallback.
 *
 * - `fill` / `fillBottom`: the store's configured `primary_color`.
 * - `onFill`: white text and icons on colored controls.
 *
 * Text and icons on white or gray use the neutral text tokens, never a brand
 * tint (S9, 2026-10-22): the store color only appears as itself, as a fill.
 */
interface BrandTheme {
  fill: string
  fillBottom: string
  onFill: string
  /** True when the store did not pick a color and the Shifty orange is used. */
  isDefault: boolean
}

const HEX_COLOR = /^#([\da-f]{3}|[\da-f]{6})$/i
// The backend stores #000000 when a store never picked a color
// (`modules/stores/model.py`). It means "not chosen", not "black on purpose".
const UNSET_STORE_COLOR = '#000000'
const WHITE = colors2000s.text.onOrangeSelection
export const DEFAULT_BRAND_THEME: BrandTheme = {
  fill: colors2000s.orange.light,
  fillBottom: colors2000s.orange.dark,
  onFill: WHITE,
  isDefault: true
}

const expandHex = (hex: string): string =>
  hex.length === 4 ? `#${[...hex.slice(1)].map((digit) => digit + digit).join('')}` : hex

const toRgb = (hex: string): [number, number, number] => {
  const full = expandHex(hex)
  return [1, 3, 5].map((offset) => parseInt(full.slice(offset, offset + 2), 16)) as [
    number,
    number,
    number
  ]
}

// El resplandor sin color de tienda sale del naranja del logo (revision de
// Enrique, 2026-10-22): una sola fuente de color para el portal.
const DEFAULT_GLOW_COLOR = `rgba(${toRgb(colors2000s.orange.dark).join(', ')}, 0.25)`

const relativeLuminance = (hex: string): number => {
  const linear = (value: number) => {
    const channel = value / 255
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  }
  const [r, g, b] = toRgb(hex)
  return 0.2126 * linear(r) + 0.7152 * linear(g) + 0.0722 * linear(b)
}

export const contrastRatio = (foreground: string, background: string): number => {
  const a = relativeLuminance(foreground)
  const b = relativeLuminance(background)
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05)
}

export const resolveBrandTheme = (primaryColor: string | null | undefined): BrandTheme => {
  const color = (primaryColor ?? '').trim()
  if (!HEX_COLOR.test(color) || expandHex(color).toLowerCase() === UNSET_STORE_COLOR) {
    return DEFAULT_BRAND_THEME
  }
  const fill = expandHex(color).toLowerCase()
  return { fill, fillBottom: fill, onFill: WHITE, isDefault: false }
}

/** CSS variables keep booking actions aligned with the store's chosen color. */
export const brandCssVariables = (theme: BrandTheme): React.CSSProperties =>
  ({
    '--brand-fill': theme.fill,
    '--brand-fill-bottom': theme.fillBottom,
    '--brand-on-fill': theme.onFill,
    ...(theme.isDefault ? {} : { '--brand-glow': `rgba(${toRgb(theme.fill).join(', ')}, 0.25)` })
  }) as React.CSSProperties

/**
 * Portada sin imagen (S9): un degradado suave del color de la tienda sobre el
 * fondo gris de la pagina. rgba precalculado, sin color-mix() (Safari < 16.2).
 */
export const brandCoverWash = (theme: BrandTheme): string => {
  const rgb = toRgb(theme.fill).join(', ')
  return `linear-gradient(135deg, rgba(${rgb}, 0.35) 0%, rgba(${rgb}, 0.75) 100%)`
}

/**
 * `var()` references to the variables `brandCssVariables` sets at the portal
 * root. Components paint with these and never compute colors themselves.
 *
 * Each one falls back to the Shifty logo orange: some booking pieces also render
 * outside the wizard root (the date and time grid in "Mis turnos"), where the
 * variables are not set and a bare `var()` would paint nothing.
 */
const fill = `var(--brand-fill, ${DEFAULT_BRAND_THEME.fill})`
const fillBottom = `var(--brand-fill-bottom, ${DEFAULT_BRAND_THEME.fillBottom})`

export const brandColor = {
  fill,
  fillBottom,
  onFill: `var(--brand-on-fill, ${DEFAULT_BRAND_THEME.onFill})`,
  fillGradient: `linear-gradient(180deg, ${fill} 0%, ${fillBottom} 100%)`
} as const

/**
 * Resplandor debajo de los controles pintados con la marca. Sin color de
 * tienda no hay `--brand-glow` y queda la sombra naranja de siempre
 * (`shadows.outerOrange`).
 */
export const brandGlowShadow = `0 2px 4px var(--brand-glow, ${DEFAULT_GLOW_COLOR})`

/** Primary action of the portal (continue, confirm, pay) on the brand fill. */
export const brandCtaStyle: React.CSSProperties = {
  background: brandColor.fillGradient,
  borderColor: brandColor.fillBottom,
  color: brandColor.onFill,
  boxShadow: `${colors2000s.shadows.insetLight}, ${brandGlowShadow}`
}

/** `buttonStyles2000s.selected` painted with the brand instead of the orange. */
export const brandSelectedStyle: React.CSSProperties = {
  ...buttonStyles2000s.selected,
  background: brandColor.fillGradient,
  border: `1px solid ${brandColor.fillBottom}`,
  color: brandColor.onFill,
  boxShadow: `${colors2000s.shadows.insetLight}, ${brandGlowShadow}`
}
