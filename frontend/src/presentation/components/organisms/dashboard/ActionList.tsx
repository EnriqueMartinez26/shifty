import EmptyState from './EmptyState'
import { toneTokens } from './toneTokens'
import type { ActionItem } from './types'
import { colors2000s } from '../../../../theme/colors'
import { createDashboardListItemStyle } from '../../../lib/surfaceStyles'

function ActionList({
  items,
  emptyText,
  compact = false
}: {
  items: ActionItem[]
  emptyText: string
  compact?: boolean
}) {
  if (!items.length) return <EmptyState text={emptyText} />

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {items.map((item) => {
        const tone = toneTokens(item.tone)
        return (
          <button
            key={item.id}
            type="button"
            onClick={item.onSelect}
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 16,
              minHeight: compact ? 64 : 72,
              ...createDashboardListItemStyle(tone.border, tone.background, compact ? 14 : 16),
              color: colors2000s.text.primary,
              cursor: item.onSelect ? 'pointer' : 'default',
              textAlign: 'left'
            }}
          >
            <span style={{ display: 'grid', gap: 4, minWidth: 0 }}>
              <strong style={{ fontSize: 14, lineHeight: '18px', fontWeight: 900 }}>
                {item.title}
              </strong>
              {item.description ? (
                <small
                  style={{
                    color: colors2000s.text.secondary,
                    fontSize: 12,
                    lineHeight: '16px',
                    fontWeight: 700
                  }}
                >
                  {item.description}
                </small>
              ) : null}
            </span>
            {item.meta ? (
              <em
                style={{
                  color: tone.accent,
                  fontSize: 12,
                  lineHeight: '16px',
                  fontStyle: 'normal',
                  whiteSpace: 'nowrap',
                  fontWeight: 900
                }}
              >
                {item.meta}
              </em>
            ) : null}
          </button>
        )
      })}
    </div>
  )
}

export default ActionList
