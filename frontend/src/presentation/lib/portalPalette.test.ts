declare const __dirname: string

const { readdirSync, readFileSync, statSync } = jest.requireActual<{
  readdirSync: (path: string) => string[]
  readFileSync: (path: string, encoding: 'utf8') => string
  statSync: (path: string) => { isFile: () => boolean }
}>('node:fs')
const { join, relative, resolve } = jest.requireActual<{
  join: (...paths: string[]) => string
  relative: (from: string, to: string) => string
  resolve: (...paths: string[]) => string
}>('node:path')

/**
 * El portal publico cierra con una sola fuente de color: el token Shifty
 * `brand-accent` (`--color-brand-accent` en src/index.css, que
 * colors.contrast.test.ts ata a colors2000s.orange.accent). Una utilidad
 * `orange-*` de Tailwind es un naranja aparte de la paleta centralizada,
 * aunque hoy src/index.css la remapee (review de PR #250).
 */
const PRESENTATION_DIR = resolve(__dirname, '..')

const PORTAL_ROOTS = [
  'components/organisms/storefront',
  'components/organisms/booking',
  'pages/PublicBooking.tsx'
]

const isSourceFile = (path: string): boolean => /\.tsx?$/.test(path) && !/\.test\.tsx?$/.test(path)

const collectSources = (path: string): string[] => {
  if (statSync(path).isFile()) return isSourceFile(path) ? [path] : []
  return readdirSync(path).flatMap((entry) => collectSources(join(path, entry)))
}

const portalSources = PORTAL_ROOTS.flatMap((root) => collectSources(join(PRESENTATION_DIR, root)))

const matchesIn = (pattern: RegExp): string[] =>
  portalSources.flatMap((file) => {
    const name = relative(PRESENTATION_DIR, file).replace(/\\/g, '/')
    return readFileSync(file, 'utf8')
      .split('\n')
      .flatMap((line, index) =>
        Array.from(line.matchAll(pattern), (match) => `${name}:${index + 1} ${match[0]}`)
      )
  })

describe('paleta del portal publico', () => {
  it('lee los archivos del portal', () => {
    expect(portalSources.length).toBeGreaterThan(10)
    expect(portalSources.some((file) => file.endsWith('StoreHeader.tsx'))).toBe(true)
    expect(portalSources.some((file) => file.endsWith('PublicBooking.tsx'))).toBe(true)
  })

  it('no usa utilidades orange-* de Tailwind', () => {
    expect(matchesIn(/\borange-\d+\b/g)).toEqual([])
  })

  it('pinta los anillos de foco con el acento Shifty', () => {
    const focusColors = matchesIn(
      /\bfocus(?:-visible)?:(?:ring|outline)-(?!none\b|offset-|\d)[\w-]+/g
    )
    expect(focusColors.length).toBeGreaterThan(0)
    expect(focusColors.filter((match) => !/:(?:ring|outline)-brand-accent$/.test(match))).toEqual(
      []
    )
  })
})
