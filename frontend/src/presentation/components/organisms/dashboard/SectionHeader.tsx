import type { ReactNode } from 'react'

import { subtleTextStyle } from './dashboardStyles'
import { colors2000s } from '../../../../theme/colors'

function SectionHeader({
  icon,
  title,
  description
}: {
  icon: ReactNode
  title: string
  description: string
}) {
  return (
    <header style={{ display: 'grid', gap: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
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
            boxShadow: colors2000s.shadows.insetLight
          }}
        >
          {icon}
        </span>
        <div style={{ display: 'grid', gap: 2 }}>
          <h3
            style={{
              margin: 0,
              color: colors2000s.text.primary,
              fontSize: 18,
              lineHeight: '22px',
              fontWeight: 900,
              letterSpacing: '-0.02em'
            }}
          >
            {title}
          </h3>
          <p style={{ margin: 0, ...subtleTextStyle }}>{description}</p>
        </div>
      </div>
    </header>
  )
}

export default SectionHeader
