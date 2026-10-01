import { ListChecks } from 'lucide-react'

import { panelBodyStyle } from './dashboardStyles'
import EmptyState from './EmptyState'
import SectionHeader from './SectionHeader'
import { toneTokens } from './toneTokens'
import type { TransactionItem } from './types'
import { buttonStyles2000s, colors2000s } from '../../../../theme/colors'
import { createDashboardListItemStyle, createDashboardPanelStyle } from '../../../lib/surfaceStyles'

function TransactionsPanel({
  title,
  description,
  items,
  emptyText,
  viewAllLabel,
  onViewAll
}: {
  title: string
  description: string
  items: TransactionItem[]
  emptyText: string
  viewAllLabel: string
  onViewAll: () => void
}) {
  return (
    <section style={createDashboardPanelStyle()}>
      <div style={{ ...panelBodyStyle, display: 'grid', gap: 16 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: 12
          }}
        >
          <SectionHeader icon={<ListChecks size={18} />} title={title} description={description} />
        </div>

        {items.length ? (
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
                    gap: 12,
                    ...createDashboardListItemStyle(tone.border, 'rgba(255, 255, 255, 0.68)', 12)
                  }}
                >
                  <span style={{ display: 'grid', gap: 4, minWidth: 0 }}>
                    <strong
                      style={{
                        fontSize: 13,
                        lineHeight: '17px',
                        fontWeight: 900,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap'
                      }}
                    >
                      {item.title}
                    </strong>
                    {item.subtitle ? (
                      <small
                        style={{
                          color: colors2000s.text.secondary,
                          fontSize: 11,
                          lineHeight: '14px',
                          fontWeight: 700,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap'
                        }}
                      >
                        {item.subtitle}
                      </small>
                    ) : null}
                    <span
                      style={{
                        alignSelf: 'start',
                        padding: '3px 8px',
                        borderRadius: 999,
                        background: tone.background,
                        color: tone.accent,
                        fontSize: 9,
                        lineHeight: '11px',
                        fontWeight: 900,
                        letterSpacing: '0.06em',
                        textTransform: 'uppercase'
                      }}
                    >
                      {item.status}
                    </span>
                  </span>

                  <strong
                    style={{
                      color: colors2000s.text.primary,
                      fontSize: 13,
                      lineHeight: '17px',
                      fontWeight: 900,
                      whiteSpace: 'nowrap'
                    }}
                  >
                    {item.amount}
                  </strong>
                </div>
              )
            })}
          </div>
        ) : (
          <EmptyState text={emptyText} />
        )}

        <button
          type="button"
          onClick={onViewAll}
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
            color: colors2000s.orange.accent
          }}
        >
          {viewAllLabel}
        </button>
      </div>
    </section>
  )
}

export default TransactionsPanel
