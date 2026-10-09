import { emptyStyle, panelBodyStyle } from './dashboardStyles'
import { createDashboardPanelStyle } from '../../../lib/surfaceStyles'

/**
 * Lugar reservado mientras baja el chunk de un grafico: el mismo panel y el
 * alto de su area de dibujo, para que la grilla no salte cuando llega.
 */
function ChartPlaceholder({ text, height }: { text: string; height: number }) {
  return (
    <section style={createDashboardPanelStyle()} aria-busy="true">
      <div style={panelBodyStyle}>
        <p style={{ ...emptyStyle, height, display: 'grid', placeItems: 'center' }}>{text}</p>
      </div>
    </section>
  )
}

export default ChartPlaceholder
