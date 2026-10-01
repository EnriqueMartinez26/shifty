import { subtleTextStyle } from './dashboardStyles'
import { toneTokens } from './toneTokens'
import type { HealthItem } from './types'
import { colors2000s } from '../../../../theme/colors'

function HealthPill({ item }: { item: HealthItem }) {
  const tone = toneTokens(item.tone)

  return (
    <div
      style={{
        padding: '14px 16px',
        borderRadius: 4,
        background: tone.background,
        boxShadow: colors2000s.shadows.insetLight,
        display: 'grid',
        gap: 4
      }}
    >
      <span style={{ ...subtleTextStyle, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        {item.label}
      </span>
      <strong style={{ color: tone.accent, fontSize: 14, lineHeight: '18px', fontWeight: 900 }}>
        {item.value}
      </strong>
    </div>
  )
}

export default HealthPill
