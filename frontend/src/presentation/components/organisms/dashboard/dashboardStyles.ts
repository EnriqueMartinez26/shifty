import type { CSSProperties } from 'react'

import { colors2000s } from '../../../../theme/colors'
import { createDashboardPanelStyle } from '../../../lib/surfaceStyles'

export const pageStyle: CSSProperties = {
  display: 'grid',
  gap: 24,
  color: colors2000s.text.primary
}

export const metricGridStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(184px, 1fr))',
  gap: 16
}

export const boardGridStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'minmax(0, 1.9fr) minmax(320px, 1fr)',
  gap: 16,
  alignItems: 'start'
}

export const lowerGridStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'minmax(0, 1.1fr) minmax(0, 1fr) minmax(0, 0.9fr)',
  gap: 16,
  alignItems: 'start'
}

export const insightsGridStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'minmax(0, 2fr) minmax(260px, 1fr) minmax(260px, 1fr)',
  gap: 16,
  alignItems: 'start'
}

export const panelBodyStyle: CSSProperties = {
  padding: 24
}

export const metricPanelStyle: CSSProperties = {
  ...createDashboardPanelStyle(),
  padding: 0
}

export const metricPanelBodyStyle: CSSProperties = {
  ...panelBodyStyle,
  display: 'grid',
  gap: 20,
  background: [
    'linear-gradient(135deg, rgba(255, 255, 255, 0.72), rgba(255, 255, 255, 0.48))',
    'radial-gradient(circle at top left, rgba(255, 140, 66, 0.12), transparent 32%)'
  ].join(', ')
}

export const subtleTextStyle: CSSProperties = {
  color: colors2000s.text.secondary,
  fontSize: 12,
  lineHeight: '16px',
  fontWeight: 700
}

export const headlineStyle: CSSProperties = {
  margin: 0,
  fontSize: 28,
  lineHeight: '32px',
  fontWeight: 900,
  color: colors2000s.text.primary,
  letterSpacing: '-0.02em',
  textTransform: 'uppercase'
}

export const emptyStyle: CSSProperties = {
  margin: 0,
  padding: 16,
  borderRadius: 6,
  border: `1px dashed ${colors2000s.border.default}`,
  background: 'rgba(255, 255, 255, 0.45)',
  color: colors2000s.text.secondary,
  fontSize: 12,
  lineHeight: '16px',
  fontWeight: 700
}
