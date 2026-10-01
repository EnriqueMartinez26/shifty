/** The value as jsdom normalizes it (hex to rgb), so it can be compared with `element.style`. */
export const cssValue = (property: 'color' | 'border' | 'borderTop', value: string): string => {
  const probe = document.createElement('div')
  probe.style[property] = value
  return probe.style[property]
}
