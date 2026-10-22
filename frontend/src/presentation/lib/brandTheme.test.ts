import {
  brandCssVariables,
  contrastRatio,
  DEFAULT_BRAND_THEME,
  resolveBrandTheme
} from './brandTheme'
import { colors2000s } from '../../theme/colors'

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
    expect(contrastRatio(theme.ink, '#ffffff')).toBeGreaterThanOrEqual(4.5)
  })

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
