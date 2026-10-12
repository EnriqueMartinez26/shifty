/** Elige blanco o negro para maximizar el contraste sobre un color configurable. */
export const getContrastingForeground = (background: string): string => {
  const normalized = /^#([\da-f]{3}|[\da-f]{6})$/i.test(background)
    ? background.length === 4
      ? `#${[...background.slice(1)].map((digit) => digit + digit).join('')}`
      : background
    : '#ffffff'
  const channel = (offset: number) => parseInt(normalized.slice(offset, offset + 2), 16) / 255
  const linear = (value: number) =>
    value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  const luminance =
    0.2126 * linear(channel(1)) + 0.7152 * linear(channel(3)) + 0.0722 * linear(channel(5))
  const contrastWithBlack = (luminance + 0.05) / 0.05
  const contrastWithWhite = 1.05 / (luminance + 0.05)

  return contrastWithBlack >= contrastWithWhite ? '#000000' : '#ffffff'
}
