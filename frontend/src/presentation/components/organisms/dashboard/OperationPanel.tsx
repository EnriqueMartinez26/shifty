import { CalendarClock, Clock3 } from 'lucide-react'

import AgendaList from './AgendaList'
import DashboardSignalCard from './DashboardSignalCard'
import { panelBodyStyle, subtleTextStyle } from './dashboardStyles'
import SectionHeader from './SectionHeader'
import type { AgendaItem, DashboardOperationCard } from './types'
import { colors2000s } from '../../../../theme/colors'
import { createDashboardPanelStyle } from '../../../lib/surfaceStyles'

function OperationPanel({
  title,
  description,
  agenda,
  emptyAgendaText,
  cards
}: {
  title: string
  description: string
  agenda: AgendaItem[]
  emptyAgendaText: string
  cards: DashboardOperationCard[]
}) {
  return (
    <section style={createDashboardPanelStyle()}>
      <div style={{ ...panelBodyStyle, display: 'grid', gap: 20 }}>
        <SectionHeader icon={<CalendarClock size={18} />} title={title} description={description} />

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(0, 1.3fr) minmax(240px, 0.9fr)',
            gap: 16
          }}
          className="dashboard-operations-inner"
        >
          <div style={{ display: 'grid', gap: 12 }}>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                gap: 12,
                padding: '12px 16px',
                borderRadius: 6,
                background: 'rgba(255, 255, 255, 0.72)',
                boxShadow: colors2000s.shadows.insetLight
              }}
            >
              <div style={{ display: 'grid', gap: 2 }}>
                <strong
                  style={{
                    fontSize: 13,
                    lineHeight: '18px',
                    fontWeight: 900,
                    color: colors2000s.text.primary
                  }}
                >
                  Proximos movimientos de agenda
                </strong>
                <span style={subtleTextStyle}>
                  Lo inmediato, antes de abrir el calendario completo.
                </span>
              </div>
              <Clock3 size={18} color={colors2000s.orange.accent} />
            </div>

            <AgendaList items={agenda} emptyText={emptyAgendaText} />
          </div>

          <div style={{ display: 'grid', gap: 12 }}>
            {cards.map((card) => (
              <DashboardSignalCard key={card.title} card={card} />
            ))}
          </div>
        </div>

        <style>
          {`
            @media (max-width: 900px) {
              .dashboard-operations-inner {
                grid-template-columns: 1fr !important;
              }
            }
          `}
        </style>
      </div>
    </section>
  )
}

export default OperationPanel
