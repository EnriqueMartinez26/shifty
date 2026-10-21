import {
  brandCssVariables,
  contrastRatio,
  DEFAULT_BRAND_THEME,
  resolveBrandTheme
} from './brandTheme'

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

  // 2026-10-22 (#240): el naranja de CTA y seleccion paso a una rampa oscura
  // con texto blanco; el tema por defecto tiene que seguir esa rampa entera.
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
