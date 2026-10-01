import { ArrowUpRight } from 'lucide-react'

import { subtleTextStyle } from './dashboardStyles'
import { toneTokens } from './toneTokens'
import type { MetricItem } from './types'
import { colors2000s } from '../../../../theme/colors'

function MetricCard({ item, emphasis = false }: { item: MetricItem; emphasis?: boolean }) {
  const tone = toneTokens(item.tone)

  return (
    <button
      type="button"
      onClick={item.onSelect}
      style={{
        display: 'grid',
        gap: emphasis ? 12 : 8,
        minHeight: emphasis ? 164 : 112,
        padding: emphasis ? 18 : 16,
        background: emphasis
          ? [
              'linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(255, 255, 255, 0.82))',
              tone.background
            ].join(', ')
          : 'rgba(255, 255, 255, 0.65)',
        border: `1px solid ${tone.border}`,
        borderRadius: 6,
        boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
        color: colors2000s.text.primary,
        textAlign: 'left',
        cursor: item.onSelect ? 'pointer' : 'default',
        position: 'relative'
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 10
        }}
      >
        <div style={{ display: 'grid', gap: 8 }}>
          <span style={{ ...subtleTextStyle, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            {item.label}
          </span>
          {item.signal ? (
            <span
              style={{
                alignSelf: 'start',
                padding: '4px 8px',
                borderRadius: 999,
                background: 'rgba(255, 255, 255, 0.74)',
                color: tone.accent,
                fontSize: 10,
                lineHeight: '12px',
                fontWeight: 900,
                textTransform: 'uppercase',
                letterSpacing: '0.08em'
              }}
            >
              {item.signal}
            </span>
          ) : null}
        </div>

        {item.icon ? (
          <span
            style={{
              width: emphasis ? 40 : 34,
              height: emphasis ? 40 : 34,
              borderRadius: 6,
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'rgba(255, 255, 255, 0.86)',
              color: tone.accent,
              boxShadow: colors2000s.shadows.insetLight,
              flexShrink: 0
            }}
          >
            {item.icon}
          </span>
        ) : null}
      </div>
      <strong
        style={{
          color: item.tone === 'primary' ? colors2000s.orange.accent : colors2000s.text.primary,
          fontSize: emphasis ? 32 : 26,
          lineHeight: emphasis ? '36px' : '30px',
          fontWeight: 900,
          letterSpacing: '-0.03em'
        }}
      >
        {item.value}
      </strong>
      {item.detail ? (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 10,
            marginTop: 'auto',
            paddingTop: emphasis ? 8 : 0
          }}
        >
          <span style={{ color: tone.accent, fontSize: 12, lineHeight: '16px', fontWeight: 800 }}>
            {item.detail}
          </span>
          {emphasis ? <ArrowUpRight size={14} color={tone.accent} /> : null}
        </div>
      ) : null}
    </button>
  )
}

export default MetricCard
