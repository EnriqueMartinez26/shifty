import EmptyState from './EmptyState'
import { toneTokens } from './toneTokens'
import type { AgendaItem } from './types'
import { colors2000s } from '../../../../theme/colors'
import { createDashboardListItemStyle } from '../../../lib/surfaceStyles'

function AgendaList({ items, emptyText }: { items: AgendaItem[]; emptyText: string }) {
  if (!items.length) return <EmptyState text={emptyText} />

  return (
    <div style={{ display: 'grid', gap: 10 }}>
      {items.map((item) => {
        const tone = toneTokens(item.tone)

        return (
          <div
            key={item.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 16,
              minHeight: 74,
              ...createDashboardListItemStyle(tone.border, 'rgba(255, 255, 255, 0.68)', 14)
            }}
          >
            <div
              style={{
                width: 60,
                alignSelf: 'stretch',
                borderRadius: 6,
                display: 'grid',
                placeItems: 'center',
                background: tone.background
              }}
            >
              <time
                style={{ color: tone.accent, fontSize: 14, lineHeight: '18px', fontWeight: 900 }}
              >
                {item.time}
              </time>
            </div>

            <span style={{ display: 'grid', gap: 4, minWidth: 0, flex: 1 }}>
              <strong style={{ fontSize: 14, lineHeight: '18px', fontWeight: 900 }}>
                {item.title}
              </strong>
              {item.subtitle ? (
                <small
                  style={{
                    color: colors2000s.text.secondary,
                    fontSize: 12,
                    lineHeight: '16px',
                    fontWeight: 700
                  }}
                >
                  {item.subtitle}
                </small>
              ) : null}
            </span>

            {item.status ? (
              <span
                style={{
                  padding: '6px 10px',
                  borderRadius: 999,
                  background: tone.background,
                  color: tone.accent,
                  fontSize: 10,
                  lineHeight: '12px',
                  fontWeight: 900,
                  letterSpacing: '0.08em',
                  textTransform: 'uppercase',
                  whiteSpace: 'nowrap'
                }}
              >
                {item.status}
              </span>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

export default AgendaList
