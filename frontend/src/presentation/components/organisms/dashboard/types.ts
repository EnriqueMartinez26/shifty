import type { ReactNode } from 'react'

import type { ReportTopServiceItem, ReportTrendPoint } from '@application/services/ReportsService'

export type Tone = 'neutral' | 'primary' | 'warning' | 'danger' | 'success'

export type MetricItem = {
  id: string
  label: string
  value: ReactNode
  detail?: ReactNode
  signal?: string
  icon?: ReactNode
  tone?: Tone
  onSelect?: () => void
}

export type ActionItem = {
  id: string
  title: string
  description?: string
  meta?: string
  tone?: Tone
  onSelect?: () => void
}

export type AgendaItem = {
  id: string
  /** dd/MM en hora argentina: la lista puede abarcar varios dias. */
  day?: string
  time: string
  title: string
  subtitle?: string
  status?: string
  tone?: Tone
}

export type RankedItem = {
  id: string
  label: string
  value: ReactNode
  detail?: ReactNode
}

export type TransactionItem = {
  id: string
  title: string
  subtitle?: string
  amount: string
  status: string
  tone?: Tone
}

export type HealthItem = {
  id: string
  label: string
  value: string
  tone?: Tone
}

export type OpportunityItem = {
  id: string
  title: string
  description: string
  tone?: Tone
  actionLabel?: string
  onSelect?: () => void
}

export type DashboardHero = {
  title: string
  description: string
  periodLabel: string
  statusLabel: string
  health: HealthItem[]
  quickActions: ActionItem[]
}

export type DashboardCopy = {
  metricsTitle: string
  transactionsTitle: string
  transactionsDescription: string
  viewTransactionsLabel: string
  operationsTitle: string
  operationsDescription: string
  actionsTitle: string
  moneyTitle: string
  performanceTitle: string
  alertsTitle: string
  opportunitiesTitle: string
  emptyActions: string
  emptyAgenda: string
  emptyAlerts: string
  emptyOpportunities: string
  emptyTransactions: string
}

export type DashboardOperationCard = {
  title: string
  detail: string
  meta: string
  tone?: Tone
}

export type EnterpriseDashboardProps = {
  copy: DashboardCopy
  hero: DashboardHero
  trendPoints: ReportTrendPoint[]
  trendLoading: boolean
  topServices: ReportTopServiceItem[]
  salesLoading: boolean
  transactions: TransactionItem[]
  onViewTransactions: () => void
  todayMetrics: MetricItem[]
  urgentActions: ActionItem[]
  agenda: AgendaItem[]
  operationCards: DashboardOperationCard[]
  moneyMetrics: MetricItem[]
  performanceItems: RankedItem[]
  alerts: ActionItem[]
  opportunities: OpportunityItem[]
  isLoading: boolean
  errorMessage?: string
}
