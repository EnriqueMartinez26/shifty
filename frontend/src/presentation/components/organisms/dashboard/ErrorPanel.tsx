import { panelBodyStyle } from './dashboardStyles'
import { createDashboardPanelStyle } from '../../../lib/surfaceStyles'

function ErrorPanel({ message }: { message: string }) {
  return (
    <div
      style={{
        ...createDashboardPanelStyle(),
        ...panelBodyStyle,
        borderColor: 'rgba(239, 68, 68, 0.42)',
        color: '#d13b3b',
        fontSize: 14,
        lineHeight: '20px',
        fontWeight: 800
      }}
    >
      {message}
    </div>
  )
}

export default ErrorPanel
