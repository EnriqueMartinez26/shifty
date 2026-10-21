import { colors2000s } from './colors'

declare const __dirname: string

const { readFileSync } = jest.requireActual<{
  readFileSync: (path: string, encoding: 'utf8') => string
}>('node:fs')
const { resolve } = jest.requireActual<{ resolve: (...paths: string[]) => string }>('node:path')

// 2026-10-03: blanco sobre el naranja de marca (#ff8c42/#e67e22) medía
// 2.31/2.85:1, text.secondary 3.0-3.4:1 sobre el fondo y el pie del portal
// usaba text.disabled (1.72:1). Por eso marca decorativa y CTA legible son
// roles distintos. Este test fija WCAG 2.1 AA para cada par de tokens de
// texto: 4.5:1, aunque el texto grande se conforme con 3:1; los mismos
// tokens van en etiquetas de 10 px. text.disabled queda fuera a propósito:
// solo se usa en controles deshabilitados, que WCAG exime (1.4.3).

const AA_NORMAL = 4.5
const AA_LARGE = 3

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
// bg.secondary, el pie cae sobre el extremo más oscuro), el hover y surface.white.
const LIGHT_SURFACES = {
  'surface.white': colors2000s.surface.white,
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
  'orange.accent': colors2000s.orange.accent,
  'status.success.text': colors2000s.status.success.text,
  'status.danger.text': colors2000s.status.danger.text,
  'status.warning.text': colors2000s.status.warning.text,
  'status.info.text': colors2000s.status.info.text
}

const lightPairs = Object.entries(TEXT_ON_LIGHT).flatMap(([text, fg]) =>
  Object.entries(LIGHT_SURFACES).map(([surface, bg]) => [text, fg, surface, bg] as const)
)

// El CTA y todo lo "seleccionado": texto oscuro sobre la rampa naranja
// orange.cta -> orange.dark (buttonStyles2000s.selected, orangeCtaGradient).
const ctaPairs = [
  [
    'text.onOrangeSelection',
    colors2000s.text.onOrangeSelection,
    'orange.cta',
    colors2000s.orange.cta
  ],
  [
    'text.onOrangeSelection',
    colors2000s.text.onOrangeSelection,
    'orange.dark',
    colors2000s.orange.dark
  ]
] as const

const statusPairs = (['success', 'danger', 'warning', 'info'] as const).flatMap((tone) => {
  const color = colors2000s.status[tone]
  return [
    [`status.${tone}.text`, color.text, `status.${tone}.bg`, color.bg] as const,
    [`status.${tone}.text`, color.text, `status.${tone}.border`, color.border] as const
  ]
})

// Los avatares azules de admin, recurso y agenda llevan iniciales blancas.
// Usan los extremos oscuros del degradado; `status.info.light` no alcanza AA.
const infoAvatarPairs = [
  ['white initials', colors2000s.text.onOrange, 'status.info.dark', colors2000s.status.info.dark],
  [
    'white initials',
    colors2000s.text.onOrange,
    'status.info.accent',
    colors2000s.status.info.accent
  ]
] as const

describe('contraste de los tokens de texto (WCAG 2.1 AA)', () => {
  it('calcula la razón de contraste como WCAG', () => {
    expect(contrast('#ffffff', '#000000')).toBeCloseTo(21, 5)
    expect(contrast('#777777', '#ffffff')).toBeCloseTo(4.48, 2)
    expect(() => luminance('#fff')).toThrow()
  })

  it.each([...lightPairs, ...ctaPairs, ...statusPairs, ...infoAvatarPairs])(
    '%s (%s) sobre %s (%s) llega a 4.5:1',
    (_text, fg, _surface, bg) => {
      expect(contrast(fg, bg)).toBeGreaterThanOrEqual(AA_NORMAL)
    }
  )

  it('mantiene contraste AA para títulos grandes sobre el fondo de página', () => {
    expect(contrast(colors2000s.orange.heading, colors2000s.bg.primary)).toBeGreaterThanOrEqual(
      AA_LARGE
    )
    expect(contrast(colors2000s.orange.heading, colors2000s.bg.secondary)).toBeGreaterThanOrEqual(
      AA_LARGE
    )
  })

  it('mantiene el tema activo de Tailwind alineado con los tokens canónicos', () => {
    const activeTheme = readFileSync(resolve(__dirname, '../index.css'), 'utf8')
    const tailwindToken = (name: string) => {
      const value = new RegExp(`--color-${name}:\\s*(#[0-9a-f]{6})`, 'i').exec(activeTheme)?.[1]
      if (!value) throw new Error(`No se encontró --color-${name} en src/index.css`)
      return value.toLowerCase()
    }

    expect(tailwindToken('primary')).toBe(colors2000s.orange.cta)
    expect(tailwindToken('primary-foreground')).toBe(colors2000s.text.onOrangeSelection)
    expect(tailwindToken('background')).toBe(colors2000s.bg.primary)
    expect(tailwindToken('background-end')).toBe(colors2000s.bg.secondary)
    expect(tailwindToken('foreground')).toBe(colors2000s.text.primary)
    expect(tailwindToken('card-foreground')).toBe(colors2000s.text.primary)
    expect(tailwindToken('card')).toBe(colors2000s.surface.white)
    expect(tailwindToken('brand-light')).toBe(colors2000s.orange.light)
    expect(tailwindToken('brand')).toBe(colors2000s.orange.dark)
    expect(tailwindToken('brand-accent')).toBe(colors2000s.orange.accent)
    expect(tailwindToken('surface')).toBe(colors2000s.bg.button)
    expect(tailwindToken('surface-subtle')).toBe(colors2000s.bg.buttonBottom)
    expect(tailwindToken('success')).toBe(colors2000s.status.success.text)
    expect(tailwindToken('success-background')).toBe(colors2000s.status.success.bg)
    expect(tailwindToken('warning')).toBe(colors2000s.status.warning.text)
    expect(tailwindToken('warning-background')).toBe(colors2000s.status.warning.bg)
    expect(tailwindToken('danger')).toBe(colors2000s.status.danger.text)
    expect(tailwindToken('danger-background')).toBe(colors2000s.status.danger.bg)
    expect(tailwindToken('info')).toBe(colors2000s.status.info.text)
    expect(tailwindToken('info-background')).toBe(colors2000s.status.info.bg)

    const legacyAliases: Record<string, string> = {
      'orange-400': colors2000s.orange.accent,
      'orange-500': colors2000s.orange.accent,
      'orange-600': colors2000s.orange.accent,
      'orange-700': colors2000s.orange.accent,
      'orange-900': colors2000s.orange.accent,
      'red-50': colors2000s.status.danger.bg,
      'red-200': colors2000s.status.danger.border,
      'red-600': colors2000s.status.danger.text,
      'red-700': colors2000s.status.danger.text,
      'green-500': colors2000s.status.success.text,
      'green-600': colors2000s.status.success.text,
      'green-700': colors2000s.status.success.text,
      'green-900': colors2000s.status.success.text,
      'emerald-200': colors2000s.status.success.border,
      'emerald-500': colors2000s.status.success.text,
      'emerald-600': colors2000s.status.success.text,
      'emerald-700': colors2000s.status.success.text,
      'amber-500': colors2000s.status.warning.text,
      'amber-700': colors2000s.status.warning.text,
      'amber-800': colors2000s.status.warning.text,
      'amber-900': colors2000s.status.warning.text,
      'blue-500': colors2000s.status.info.text
    }
    for (const [utility, color] of Object.entries(legacyAliases)) {
      expect(tailwindToken(utility)).toBe(color)
    }

    expect(
      contrast(tailwindToken('primary-foreground'), tailwindToken('primary'))
    ).toBeGreaterThanOrEqual(AA_NORMAL)
  })
})
