import { emptyStyle } from './dashboardStyles'

function EmptyState({ text }: { text: string }) {
  return <p style={emptyStyle}>{text}</p>
}

export default EmptyState
