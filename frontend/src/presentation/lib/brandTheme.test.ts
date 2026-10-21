import {
  brandColor,
  brandCssVariables,
  brandCtaStyle,
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
    'keeps AA for text on the fill and for brand text on white (%s)',
    (value) => {
      const theme = resolveBrandTheme(value)
      expect(theme.isDefault).toBe(false)
      expect(contrastRatio(theme.onFill, theme.fill)).toBeGreaterThanOrEqual(4.5)
      expect(contrastRatio(theme.onFill, theme.fillBottom)).toBeGreaterThanOrEqual(4.5)
      expect(contrastRatio(theme.ink, '#ffffff')).toBeGreaterThanOrEqual(4.5)
    }
  )

  it('keeps the store color as the fill and darkens only the ink', () => {
    const theme = resolveBrandTheme('#FF70FA')
    expect(theme.fill).toBe('#ff70fa')
    expect(theme.onFill).toBe('#000000')
    expect(theme.ink).not.toBe('#ff70fa')
  })

  it('keeps a dark color as its own ink', () => {
    expect(resolveBrandTheme('#1d4ed8').ink).toBe('#1d4ed8')
  })

  it('exposes the theme as CSS custom properties', () => {
    expect(brandCssVariables(resolveBrandTheme('#3b82f6'))).toEqual({
      '--brand-fill': '#3b82f6',
      '--brand-fill-bottom': expect.stringMatching(/^#[\da-f]{6}$/),
      '--brand-on-fill': expect.stringMatching(/^#(000000|ffffff)$/),
      '--brand-ink': expect.stringMatching(/^#[\da-f]{6}$/)
    })
  })
})

describe('brand variable references', () => {
  it('point at the custom properties the portal root sets, with the orange as fallback', () => {
    const defaults = brandCssVariables(DEFAULT_BRAND_THEME) as Record<string, string>
    expect([brandColor.fill, brandColor.fillBottom, brandColor.onFill, brandColor.ink]).toEqual(
      Object.entries(defaults).map(([name, value]) => `var(${name}, ${value})`)
    )
    expect(brandColor.fill).toBe(`var(--brand-fill, ${colors2000s.orange.cta})`)
    expect(brandColor.ink).toBe(`var(--brand-ink, ${colors2000s.orange.accent})`)
    expect(brandColor.fillGradient).toBe(
      `linear-gradient(180deg, ${brandColor.fill} 0%, ${brandColor.fillBottom} 100%)`
    )
  })

  it('paints the primary action with the brand fill and its text', () => {
    expect(brandCtaStyle).toEqual({
      background: brandColor.fillGradient,
      borderColor: brandColor.fillBottom,
      color: brandColor.onFill,
      boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`
    })
  })

  it('paints the 2000s selected state with the brand and keeps its shape', () => {
    expect(brandSelectedStyle).toEqual({
      ...buttonStyles2000s.selected,
      background: brandColor.fillGradient,
      border: `1px solid ${brandColor.ink}`,
      color: brandColor.onFill
    })
  })
})
