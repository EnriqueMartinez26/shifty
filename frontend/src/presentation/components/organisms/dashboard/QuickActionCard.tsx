import { toneTokens } from './toneTokens'
import type { ActionItem } from './types'
import { buttonStyles2000s, colors2000s } from '../../../../theme/colors'

function QuickActionCard({ item }: { item: ActionItem }) {
  const tone = toneTokens(item.tone)

  return (
    <button
      type="button"
      onClick={item.onSelect}
      style={{
        ...buttonStyles2000s.default,
        borderRadius: 6,
        padding: 16,
        textAlign: 'left',
        display: 'grid',
        gap: 6,
        borderColor: tone.border
      }}
    >
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
      {item.description ? (
        <span
          style={{
            color: colors2000s.text.secondary,
            fontSize: 12,
            lineHeight: '16px',
            fontWeight: 700
          }}
        >
          {item.description}
        </span>
      ) : null}
    </button>
  )
}

export default QuickActionCard
