import type { ReactNode } from 'react'

import { panelBodyStyle } from './dashboardStyles'
import SectionHeader from './SectionHeader'
import { createDashboardPanelStyle } from '../../../lib/surfaceStyles'

function Panel({
  title,
  description,
  icon,
  children
}: {
  title: string
  description: string
  icon: ReactNode
  children: ReactNode
}) {
  return (
    <section style={createDashboardPanelStyle()}>
      <div style={{ ...panelBodyStyle, display: 'grid', gap: 16 }}>
        <SectionHeader icon={icon} title={title} description={description} />
        {children}
      </div>
    </section>
  )
}

export default Panel
