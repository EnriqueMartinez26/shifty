import {
  brandColor,
  brandCoverWash,
  brandCssVariables,
  brandCtaStyle,
  brandGlowShadow,
  brandSelectedStyle,
  contrastRatio,
  DEFAULT_BRAND_THEME,
  resolveBrandTheme
} from './brandTheme'
import { buttonStyles2000s, colors2000s } from '../../theme/colors'

describe('resolveBrandTheme', () => {
  it.each([null, undefined, '', 'pink', '#12345', '#000000', '#000'])(
    'uses the Shifty orange when the store has no usable color (%s)',
    (value) => {
      expect(resolveBrandTheme(value)).toEqual(DEFAULT_BRAND_THEME)
    }
  )

  it.each(['#ff70fa', '#ffff00', '#fff', '#3b82f6', '#777777', '#111111', '#e67e22', '#00ff88'])(
    'uses the configured store color unchanged for controls (%s)',
    (value) => {
      const theme = resolveBrandTheme(value)
      expect(theme.isDefault).toBe(false)
      expect(theme.fill).toBe(value.length === 4 ? '#ffffff' : value)
      expect(theme.fillBottom).toBe(theme.fill)
      expect(contrastRatio(theme.onFill, theme.fill)).toBeGreaterThanOrEqual(4.5)
    }
  )

  // 2026-10-23: la rama del naranja ponia texto blanco fijo sobre cualquier
  // color de tienda; sobre el rosa de jaziz-nails quedaba en 2.35:1.
  it('keeps dark text on a light store color', () => {
    const theme = resolveBrandTheme('#ff70fa')
    expect(theme.onFill).toBe('#000000')
    expect(contrastRatio(theme.onFill, theme.fill)).toBeGreaterThanOrEqual(4.5)
  })

  // S9 (2026-10-22): sin tinta de marca. El texto sobre blanco o gris es
  // neutro, asi que el tema solo trae el relleno y su texto.
  it('has no brand ink: only the fill and the text on it', () => {
    expect(Object.keys(resolveBrandTheme('#ffff00')).sort()).toEqual([
      'fill',
      'fillBottom',
      'isDefault',
      'onFill'
    ])
    expect(Object.keys(brandColor)).not.toContain('ink')
  })

  it('uses the logo orange ramp when no store color is configured', () => {
    expect(DEFAULT_BRAND_THEME.fill).toBe(colors2000s.orange.light)
    expect(DEFAULT_BRAND_THEME.fillBottom).toBe(colors2000s.orange.dark)
    expect(DEFAULT_BRAND_THEME.onFill).toBe('#ffffff')
  })

  it('keeps the admin-selected store color and uses a white foreground', () => {
    const theme = resolveBrandTheme('#be185d')
    expect(theme.fill).toBe('#be185d')
    expect(theme.fillBottom).toBe('#be185d')
    expect(theme.onFill).toBe('#ffffff')
    expect(contrastRatio(theme.onFill, theme.fill)).toBeGreaterThanOrEqual(4.5)
  })

  it('exposes the admin-selected color as CSS custom properties', () => {
    expect(brandCssVariables(resolveBrandTheme('#3b82f6'))).toEqual({
      '--brand-fill': '#3b82f6',
      '--brand-fill-bottom': '#3b82f6',
      '--brand-on-fill': '#000000',
      '--brand-glow': 'rgba(59, 130, 246, 0.25)'
    })
  })

  it('uses the logo orange without a store color and no custom glow', () => {
    expect(brandCssVariables(DEFAULT_BRAND_THEME)).not.toHaveProperty('--brand-glow')
    expect(brandCssVariables(DEFAULT_BRAND_THEME)).toEqual({
      '--brand-fill': colors2000s.orange.light,
      '--brand-fill-bottom': colors2000s.orange.dark,
      '--brand-on-fill': '#ffffff'
    })
  })

  // 2026-10-22 (S9): sin portada, un degradado suave del color de la tienda.
  // rgba precalculado, sin color-mix() (Safari < 16.2).
  it('builds the soft cover wash from the fill as precomputed rgba', () => {
    expect(brandCoverWash(resolveBrandTheme('#3b82f6'))).toBe(
      'linear-gradient(135deg, rgba(59, 130, 246, 0.35) 0%, rgba(59, 130, 246, 0.75) 100%)'
    )
    expect(brandCoverWash(DEFAULT_BRAND_THEME)).toContain('rgba(255, 140, 66, 0.35)')
    expect(brandCoverWash(DEFAULT_BRAND_THEME)).not.toContain('color-mix')
  })
})

describe('brand variable references', () => {
  it('point at the custom properties the portal root sets, with the orange as fallback', () => {
    const defaults = brandCssVariables(DEFAULT_BRAND_THEME) as Record<string, string>
    expect([brandColor.fill, brandColor.fillBottom, brandColor.onFill]).toEqual(
      Object.entries(defaults).map(([name, value]) => `var(${name}, ${value})`)
    )
    expect(brandColor.fill).toBe(`var(--brand-fill, ${colors2000s.orange.light})`)
    expect(brandColor.fillGradient).toBe(
      `linear-gradient(180deg, ${brandColor.fill} 0%, ${brandColor.fillBottom} 100%)`
    )
  })

  it('paints the primary action with the store color and a white foreground', () => {
    expect(brandCtaStyle).toEqual({
      background: brandColor.fillGradient,
      borderColor: brandColor.fillBottom,
      color: brandColor.onFill,
      boxShadow: `${colors2000s.shadows.insetLight}, ${brandGlowShadow}`
    })
  })

  it('the glow uses the store color and falls back to logo orange', () => {
    expect(brandGlowShadow).toBe('0 2px 4px var(--brand-glow, rgba(230, 126, 34, 0.25))')
    expect(colors2000s.orange.dark).toBe('#e67e22')
  })

  it('paints the 2000s selected state with the brand and keeps its shape', () => {
    expect(brandSelectedStyle).toEqual({
      ...buttonStyles2000s.selected,
      background: brandColor.fillGradient,
      border: `1px solid ${brandColor.fillBottom}`,
      color: brandColor.onFill,
      boxShadow: `${colors2000s.shadows.insetLight}, ${brandGlowShadow}`
    })
  })
})
