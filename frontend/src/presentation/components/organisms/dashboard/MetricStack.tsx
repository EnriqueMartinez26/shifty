import MetricCard from './MetricCard'
import type { MetricItem } from './types'

function MetricStack({ items }: { items: MetricItem[] }) {
  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {items.map((item) => (
        <MetricCard key={item.id} item={item} />
      ))}
    </div>
  )
}

export default MetricStack
