import EmptyState from './EmptyState'
import type { RankedItem } from './types'
import { colors2000s } from '../../../../theme/colors'
import { createDashboardListItemStyle } from '../../../lib/surfaceStyles'

function RankedList({ items }: { items: RankedItem[] }) {
  if (!items.length) return <EmptyState text="Sin datos para este periodo." />

  return (
    <ol style={{ display: 'grid', gap: 12, listStyle: 'none', margin: 0, padding: 0 }}>
      {items.map((item, index) => (
        <li
          key={item.id}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 14,
            minHeight: 70,
            ...createDashboardListItemStyle(
              colors2000s.border.light,
              'rgba(255, 255, 255, 0.65)',
              14
            )
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
            <span
              style={{
                width: 34,
                height: 34,
                borderRadius: 6,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'rgba(255, 140, 66, 0.12)',
                color: colors2000s.orange.accent,
                fontSize: 12,
                lineHeight: '16px',
                fontWeight: 900
              }}
            >
              {index + 1}
            </span>
            <span style={{ display: 'grid', gap: 4, minWidth: 0 }}>
              <strong style={{ fontSize: 14, lineHeight: '18px', fontWeight: 900 }}>
                {item.label}
              </strong>
              {item.detail ? (
                <small
                  style={{
                    color: colors2000s.text.secondary,
                    fontSize: 12,
                    lineHeight: '16px',
                    fontWeight: 700
                  }}
                >
                  {item.detail}
                </small>
              ) : null}
            </span>
          </div>
          <em
            style={{
              color: colors2000s.orange.accent,
              fontSize: 12,
              lineHeight: '16px',
              fontStyle: 'normal',
              whiteSpace: 'nowrap',
              fontWeight: 900
            }}
          >
            {item.value}
          </em>
        </li>
      ))}
    </ol>
  )
}

export default RankedList
