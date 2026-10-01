import EmptyState from './EmptyState'
import { toneTokens } from './toneTokens'
import type { OpportunityItem } from './types'
import { buttonStyles2000s, colors2000s } from '../../../../theme/colors'
import { createDashboardListItemStyle } from '../../../lib/surfaceStyles'

function OpportunityList({ items, emptyText }: { items: OpportunityItem[]; emptyText: string }) {
  if (!items.length) return <EmptyState text={emptyText} />

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {items.map((item) => {
        const tone = toneTokens(item.tone)
        return (
          <div
            key={item.id}
            style={{
              ...createDashboardListItemStyle(tone.border, 'rgba(255, 255, 255, 0.62)', 16),
              display: 'grid',
              gap: 10
            }}
          >
            <div style={{ display: 'grid', gap: 4 }}>
              <strong
                style={{
                  color: colors2000s.text.primary,
                  fontSize: 14,
                  lineHeight: '18px',
                  fontWeight: 900
                }}
              >
                {item.title}
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
                {item.description}
              </p>
            </div>

            {item.actionLabel && item.onSelect ? (
              <button
                type="button"
                onClick={item.onSelect}
                style={{
                  ...buttonStyles2000s.default,
                  borderRadius: 6,
                  padding: '10px 12px',
                  justifySelf: 'start',
                  fontSize: 11,
                  lineHeight: '14px',
                  fontWeight: 900,
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em',
                  color: tone.accent
                }}
              >
                {item.actionLabel}
              </button>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

export default OpportunityList
