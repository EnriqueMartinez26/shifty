import { subtleTextStyle } from './dashboardStyles'
import { toneTokens } from './toneTokens'
import type { DashboardOperationCard } from './types'
import { colors2000s } from '../../../../theme/colors'
import { createDashboardListItemStyle } from '../../../lib/surfaceStyles'

function DashboardSignalCard({ card }: { card: DashboardOperationCard }) {
  const tone = toneTokens(card.tone)

  return (
    <div
      style={{
        ...createDashboardListItemStyle(tone.border, tone.background),
        display: 'grid',
        gap: 8
      }}
    >
      <span style={{ ...subtleTextStyle, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        {card.title}
      </span>
      <strong style={{ color: tone.accent, fontSize: 22, lineHeight: '26px', fontWeight: 900 }}>
        {card.meta}
      </strong>
      <p
        style={{
          margin: 0,
          color: colors2000s.text.secondary,
          fontSize: 12,
          lineHeight: '16px',
          fontWeight: 700
        }}
      >
        {card.detail}
      </p>
    </div>
  )
}

export default DashboardSignalCard
