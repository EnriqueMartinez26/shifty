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
    'keeps AA for text on both ends of the fill (%s)',
    (value) => {
      const theme = resolveBrandTheme(value)
      expect(theme.isDefault).toBe(false)
      expect(contrastRatio(theme.onFill, theme.fill)).toBeGreaterThanOrEqual(4.5)
      expect(contrastRatio(theme.onFill, theme.fillBottom)).toBeGreaterThanOrEqual(4.5)
    }
  )

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

  // 2026-10-22 (revision de #239): el respaldo usaba la rampa oscura de CTA
  // del panel (#c04f00 -> #b84d00) y no coincidia con el naranja del logo.
  it('uses the logo orange ramp for stores without a color', () => {
    expect(DEFAULT_BRAND_THEME.fill).toBe(colors2000s.orange.light)
    expect(DEFAULT_BRAND_THEME.fillBottom).toBe(colors2000s.orange.dark)
    expect(DEFAULT_BRAND_THEME.fill).toBe('#ff8c42')
    expect(DEFAULT_BRAND_THEME.fillBottom).toBe('#e67e22')
  })

  // El texto blanco no llega a AA sobre el naranja del logo (2.31:1 y 2.85:1):
  // el texto del respaldo tiene que pasar AA en los dos extremos.
  it('keeps AA for the default Shifty orange on both ends of the fill', () => {
    const theme = DEFAULT_BRAND_THEME
    expect(contrastRatio(theme.onFill, theme.fill)).toBeGreaterThanOrEqual(4.5)
    expect(contrastRatio(theme.onFill, theme.fillBottom)).toBeGreaterThanOrEqual(4.5)
  })

  it('keeps the store color as the fill, as is', () => {
    const theme = resolveBrandTheme('#FF70FA')
    expect(theme.fill).toBe('#ff70fa')
    expect(theme.onFill).toBe('#000000')
  })

  it('exposes the theme as CSS custom properties', () => {
    expect(brandCssVariables(resolveBrandTheme('#3b82f6'))).toEqual({
      '--brand-fill': '#3b82f6',
      '--brand-fill-bottom': expect.stringMatching(/^#[\da-f]{6}$/),
      '--brand-on-fill': expect.stringMatching(/^#(000000|ffffff)$/),
      // rgba precalculado: sin color-mix(), que Safari < 16.2 no entiende y
      // anulaba toda la sombra (QA visual 2026-10-21).
      '--brand-glow': 'rgba(59, 130, 246, 0.25)'
    })
  })

  it('without a store color sets no glow, so the orange shadow stays', () => {
    expect(brandCssVariables(DEFAULT_BRAND_THEME)).not.toHaveProperty('--brand-glow')
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

  it('paints the primary action with the brand fill and its text', () => {
    expect(brandCtaStyle).toEqual({
      background: brandColor.fillGradient,
      borderColor: brandColor.fillBottom,
      color: brandColor.onFill,
      boxShadow: `${colors2000s.shadows.insetLight}, ${brandGlowShadow}`
    })
  })

  // QA 2026-10-21: el resplandor naranja quedaba debajo de un boton rosa.
  it('the glow follows the brand and falls back to the orange shadow', () => {
    expect(brandGlowShadow).toBe('0 2px 4px var(--brand-glow, rgba(200, 90, 15, 0.25))')
    expect(brandGlowShadow.replace(/var\(--brand-glow, (.+)\)$/, '$1')).toBe(
      colors2000s.shadows.outerOrange
    )
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
