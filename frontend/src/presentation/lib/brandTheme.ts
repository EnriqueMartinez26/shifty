import type React from 'react'

import { getContrastingForeground } from './getContrastingForeground'
import { buttonStyles2000s, colors2000s } from '../../theme/colors'

/**
 * Colors of a store's public portal, derived from its `primary_color`.
 *
 * - `fill` / `fillBottom`: background of primary actions and selected states.
 * - `onFill`: text and icons on the fill; AA (>= 4.5:1) against both ends.
 * - `ink`: brand-tinted text, links and borders on white and on the gray
 *   buttons and cards; AA against both.
 */
interface BrandTheme {
  fill: string
  fillBottom: string
  onFill: string
  ink: string
  /** True when the store did not pick a color and the Shifty orange is used. */
  isDefault: boolean
}

const HEX_COLOR = /^#([\da-f]{3}|[\da-f]{6})$/i
const AA_MIN_CONTRAST = 4.5
const WHITE = '#ffffff'
// El texto de marca va sobre blanco y sobre el degradado gris de botones y
// tarjetas (bg.button -> bg.buttonBottom); el fondo es el mas oscuro.
const INK_SURFACES = [WHITE, colors2000s.bg.buttonBottom] as const
// The backend stores #000000 when a store never picked a color
// (`modules/stores/model.py`). It means "not chosen", not "black on purpose".
const UNSET_STORE_COLOR = '#000000'
const GRADIENT_DARKEN = 0.1
// El color de `shadows.outerOrange`: el resplandor sin color de tienda.
const DEFAULT_GLOW_COLOR = 'rgba(200, 90, 15, 0.25)'

export const DEFAULT_BRAND_THEME: BrandTheme = {
  fill: colors2000s.orange.cta,
  fillBottom: colors2000s.orange.ctaEnd,
  onFill: colors2000s.text.onOrangeSelection,
  ink: colors2000s.orange.accent,
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

const toHex = (rgb: [number, number, number]): string =>
  `#${rgb.map((value) => Math.round(value).toString(16).padStart(2, '0')).join('')}`

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

/** Mixes the color with black; `amount` 0 keeps it, 1 is black. */
const darken = (hex: string, amount: number): string =>
  toHex(toRgb(hex).map((value) => value * (1 - amount)) as [number, number, number])

const readsOnLightSurfaces = (ink: string): boolean =>
  INK_SURFACES.every((surface) => contrastRatio(ink, surface) >= AA_MIN_CONTRAST)

/**
 * El paso mas claro en que el color se lee como texto (AA) sobre blanco y
 * sobre el gris de botones y tarjetas. Un color que ya pasa queda igual.
 */
const inkOnLightSurfaces = (hex: string): string => {
  let ink = expandHex(hex).toLowerCase()
  for (let step = 0; step < 20 && !readsOnLightSurfaces(ink); step += 1) {
    ink = darken(ink, 0.08)
  }
  return ink
}

export const resolveBrandTheme = (primaryColor: string | null | undefined): BrandTheme => {
  const color = (primaryColor ?? '').trim()
  if (!HEX_COLOR.test(color) || expandHex(color).toLowerCase() === UNSET_STORE_COLOR) {
    return DEFAULT_BRAND_THEME
  }
  const fill = expandHex(color).toLowerCase()
  const onFill = getContrastingForeground(fill)
  const darker = darken(fill, GRADIENT_DARKEN)
  // A darker bottom lowers the contrast of black text: keep the gradient only
  // when the text still passes AA on both ends.
  const fillBottom = contrastRatio(onFill, darker) >= AA_MIN_CONTRAST ? darker : fill
  return { fill, fillBottom, onFill, ink: inkOnLightSurfaces(fill), isDefault: false }
}

/** CSS custom properties for the portal root; components read `var(--brand-*)`. */
export const brandCssVariables = (theme: BrandTheme): React.CSSProperties =>
  ({
    '--brand-fill': theme.fill,
    '--brand-fill-bottom': theme.fillBottom,
    '--brand-on-fill': theme.onFill,
    '--brand-ink': theme.ink,
    // El resplandor sale del color de la tienda; sin color queda el naranja.
    // rgba precalculado y no color-mix(): Safari < 16.2 lo ignora y anulaba
    // toda la sombra (QA visual 2026-10-21).
    ...(theme.isDefault ? {} : { '--brand-glow': `rgba(${toRgb(theme.fill).join(', ')}, 0.25)` })
  }) as React.CSSProperties

/**
 * `var()` references to the variables `brandCssVariables` sets at the portal
 * root. Components paint with these and never compute colors themselves: the
 * contrast is already resolved by `resolveBrandTheme`.
 *
 * Each one falls back to the Shifty orange: some booking pieces also render
 * outside the wizard root (the date and time grid in "Mis turnos"), where the
 * variables are not set and a bare `var()` would paint nothing.
 */
const fill = `var(--brand-fill, ${DEFAULT_BRAND_THEME.fill})`
const fillBottom = `var(--brand-fill-bottom, ${DEFAULT_BRAND_THEME.fillBottom})`

export const brandColor = {
  fill,
  fillBottom,
  onFill: `var(--brand-on-fill, ${DEFAULT_BRAND_THEME.onFill})`,
  ink: `var(--brand-ink, ${DEFAULT_BRAND_THEME.ink})`,
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
  border: `1px solid ${brandColor.ink}`,
  color: brandColor.onFill,
  boxShadow: `${colors2000s.shadows.insetLight}, ${brandGlowShadow}`
}
