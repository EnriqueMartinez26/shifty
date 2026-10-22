import { formatRelative } from './relativeTime'

describe('formatRelative', () => {
  const ahora = new Date('2026-10-22T12:00:00Z').getTime()

  beforeEach(() => {
    jest.spyOn(Date, 'now').mockReturnValue(ahora)
  })

  afterEach(() => {
    jest.restoreAllMocks()
  })

  it.each([
    ['2026-10-22T11:59:30Z', 'recién'],
    ['2026-10-22T11:55:00Z', 'hace 5 min'],
    ['2026-10-22T09:00:00Z', 'hace 3 h'],
    ['2026-10-20T12:00:00Z', 'hace 2 d']
  ])('%s se muestra como "%s"', (iso, esperado) => {
    expect(formatRelative(iso)).toBe(esperado)
  })

  it('un instante ilegible no muestra nada', () => {
    expect(formatRelative('no-es-fecha')).toBe('')
  })
})
