import { headlineStyle, subtleTextStyle } from './dashboardStyles'
import HealthPill from './HealthPill'
import QuickActionCard from './QuickActionCard'
import type { DashboardHero } from './types'
import { colors2000s } from '../../../../theme/colors'
import { createDashboardPanelStyle } from '../../../lib/surfaceStyles'

function HeroPanel({ hero }: { hero: DashboardHero }) {
  return (
    <section
      style={{
        ...createDashboardPanelStyle(),
        padding: 0
      }}
    >
      <div
        style={{
          padding: 24,
          display: 'grid',
          gap: 24,
          background: [
            'radial-gradient(circle at top right, rgba(255, 140, 66, 0.18), transparent 34%)',
            `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`
          ].join(', ')
        }}
      >
        <div
          style={{ display: 'flex', justifyContent: 'space-between', gap: 24, flexWrap: 'wrap' }}
        >
          <div style={{ display: 'grid', gap: 8, minWidth: 280 }}>
            <span
              style={{ ...subtleTextStyle, textTransform: 'uppercase', letterSpacing: '0.12em' }}
            >
              {hero.periodLabel}
            </span>
            <h2 style={headlineStyle}>{hero.title}</h2>
            <p
              style={{
                margin: 0,
                color: colors2000s.text.secondary,
                fontSize: 14,
                lineHeight: '20px',
                fontWeight: 700
              }}
            >
              {hero.description}
            </p>
          </div>

          <div
            style={{
              alignSelf: 'start',
              padding: '10px 14px',
              borderRadius: 999,
              background: 'rgba(255, 255, 255, 0.9)',
              boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
              color: colors2000s.text.secondary,
              fontSize: 12,
              lineHeight: '16px',
              fontWeight: 900,
              textTransform: 'uppercase',
              letterSpacing: '0.08em'
            }}
          >
            Estado general:{' '}
            <span style={{ color: colors2000s.orange.accent }}>{hero.statusLabel}</span>
          </div>
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
            gap: 12
          }}
        >
          {hero.health.map((item) => (
            <HealthPill key={item.id} item={item} />
          ))}
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
            gap: 12
          }}
        >
          {hero.quickActions.map((item) => (
            <QuickActionCard key={item.id} item={item} />
          ))}
        </div>
      </div>
    </section>
  )
}

export default HeroPanel
