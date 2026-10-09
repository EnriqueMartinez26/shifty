import { colors2000s } from './colors'

// 2026-10-03: el CTA naranja (blanco sobre #ff8c42/#e67e22) medía 2.31/2.85:1,
// text.secondary 3.0-3.4:1 sobre el fondo y el pie del portal usaba
// text.disabled (1.72:1). Este test fija WCAG 2.1 AA para cada par de tokens
// que se usa para texto. Todos piden 4.5:1 (texto normal), aunque el texto
// grande se conforme con 3:1: los mismos tokens van en etiquetas de 10 px.
// text.disabled queda fuera a propósito: es solo para controles
// deshabilitados, que WCAG exime (1.4.3).

const AA_NORMAL = 4.5

const channel = (hex: string, offset: number): number => {
  const value = parseInt(hex.slice(offset, offset + 2), 16) / 255
  return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
}

/** Luminancia relativa de WCAG 2.1 de un color `#rrggbb`. */
const luminance = (hex: string): number => {
  if (!/^#[0-9a-f]{6}$/i.test(hex)) throw new Error(`se esperaba #rrggbb: ${hex}`)
  return 0.2126 * channel(hex, 1) + 0.7152 * channel(hex, 3) + 0.0722 * channel(hex, 5)
}

const contrast = (a: string, b: string): number => {
  const [la, lb] = [luminance(a), luminance(b)]
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05)
}

// Superficies claras donde se apoya el texto: tarjetas y botones (degradado
// bg.button -> bg.buttonBottom), el fondo de página (bg.primary ->
// bg.secondary, el pie cae sobre el extremo más oscuro), el hover y el blanco.
const LIGHT_SURFACES = {
  white: '#ffffff',
  'bg.button': colors2000s.bg.button,
  'bg.buttonBottom': colors2000s.bg.buttonBottom,
  'bg.primary': colors2000s.bg.primary,
  'bg.secondary': colors2000s.bg.secondary,
  'bg.disabled': colors2000s.bg.disabled,
  'states.hover': colors2000s.states.hover,
  'states.hoverBottom': colors2000s.states.hoverBottom
}

const TEXT_ON_LIGHT = {
  'text.primary': colors2000s.text.primary,
  'text.secondary': colors2000s.text.secondary,
  'orange.accent': colors2000s.orange.accent
}

const lightPairs = Object.entries(TEXT_ON_LIGHT).flatMap(([text, fg]) =>
  Object.entries(LIGHT_SURFACES).map(([surface, bg]) => [text, fg, surface, bg] as const)
)

// El CTA y todo lo "seleccionado": texto blanco sobre el degradado
// orange.cta -> orange.accent (buttonStyles2000s.selected, orangeCtaGradient).
const ctaPairs = [
  ['text.onOrange', colors2000s.text.onOrange, 'orange.cta', colors2000s.orange.cta],
  ['text.onOrange', colors2000s.text.onOrange, 'orange.accent', colors2000s.orange.accent]
] as const

const statusPairs = (['success', 'danger', 'warning', 'info'] as const).map(
  (tone) =>
    [
      `status.${tone}.text`,
      colors2000s.status[tone].text,
      `status.${tone}.bg`,
      colors2000s.status[tone].bg
    ] as const
)

describe('contraste de los tokens de texto (WCAG 2.1 AA)', () => {
  it('calcula la razón de contraste como WCAG', () => {
    expect(contrast('#ffffff', '#000000')).toBeCloseTo(21, 5)
    expect(contrast('#777777', '#ffffff')).toBeCloseTo(4.48, 2)
    expect(() => luminance('#fff')).toThrow()
  })

  it.each([...lightPairs, ...ctaPairs, ...statusPairs])(
    '%s (%s) sobre %s (%s) llega a 4.5:1',
    (_text, fg, _surface, bg) => {
      expect(contrast(fg, bg)).toBeGreaterThanOrEqual(AA_NORMAL)
    }
  )
})
