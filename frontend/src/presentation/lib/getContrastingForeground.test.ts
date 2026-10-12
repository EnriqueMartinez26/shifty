import { getContrastingForeground } from './getContrastingForeground'

const luminance = (hex: string): number => {
  const normalized =
    hex.length === 4 ? `#${[...hex.slice(1)].map((digit) => digit + digit).join('')}` : hex
  const channel = (offset: number) => parseInt(normalized.slice(offset, offset + 2), 16) / 255
  const linear = (value: number) =>
    value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  return 0.2126 * linear(channel(1)) + 0.7152 * linear(channel(3)) + 0.0722 * linear(channel(5))
}

const contrast = (foreground: string, background: string) => {
  const values = [luminance(foreground), luminance(background)].sort((a, b) => b - a)
  return (Math.max(...values) + 0.05) / (Math.min(...values) + 0.05)
}

describe('getContrastingForeground', () => {
  it.each(['#fff', '#ff8c42', '#ffff00', '#3b82f6', '#777777', '#000000'])(
    'mantiene contraste AA para el color configurable %s',
    (background) => {
      const foreground = getContrastingForeground(background)
      expect(contrast(foreground, background)).toBeGreaterThanOrEqual(4.5)
    }
  )

  it('normaliza hex abreviado y usa un color seguro ante una entrada inesperada', () => {
    expect(getContrastingForeground('#fff')).toBe('#000000')
    expect(getContrastingForeground('invalid')).toBe('#000000')
  })
})
