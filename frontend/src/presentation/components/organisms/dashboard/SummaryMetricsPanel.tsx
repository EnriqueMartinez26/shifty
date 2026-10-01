import { LayoutDashboard } from 'lucide-react'

import { metricGridStyle, metricPanelBodyStyle, metricPanelStyle } from './dashboardStyles'
import MetricCard from './MetricCard'
import SectionHeader from './SectionHeader'
import type { MetricItem } from './types'
import { colors2000s } from '../../../../theme/colors'

function SummaryMetricsPanel({ title, metrics }: { title: string; metrics: MetricItem[] }) {
  return (
    <section style={metricPanelStyle}>
      <div style={metricPanelBodyStyle}>
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-end',
            justifyContent: 'space-between',
            gap: 16,
            flexWrap: 'wrap'
          }}
        >
          <SectionHeader
            icon={<LayoutDashboard size={18} />}
            title={title}
            description="Cuatro senales para entender el pulso del negocio antes de entrar al detalle."
          />

          <div
            style={{
              alignSelf: 'center',
              padding: '10px 14px',
              borderRadius: 999,
              background: 'rgba(255, 255, 255, 0.76)',
              boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
              color: colors2000s.text.secondary,
              fontSize: 11,
              lineHeight: '14px',
              fontWeight: 900,
              textTransform: 'uppercase',
              letterSpacing: '0.08em'
            }}
          >
            Lectura rapida del dia
          </div>
        </div>

        <div style={metricGridStyle}>
          {metrics.map((metric) => (
            <MetricCard key={metric.id} item={metric} emphasis />
          ))}
        </div>
      </div>
    </section>
  )
}

export default SummaryMetricsPanel
