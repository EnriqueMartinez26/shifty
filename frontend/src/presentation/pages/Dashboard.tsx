import { useMemo } from 'react'
import type { CSSProperties, ReactNode } from 'react'

import { format, subDays } from 'date-fns'
import {
  ArrowUpRight,
  CalendarClock,
  CircleAlert,
  CircleDollarSign,
  Clock3,
  Gauge,
  LayoutDashboard,
  Sparkles,
  TrendingUp,
  UserRoundPlus,
  Wallet
} from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import type { UpcomingAppointment } from '@application/services/DashboardService'
import type {
  ProfessionalReportItem,
  ReportTopServiceItem
} from '@application/services/ReportsService'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { useAuth } from '../context/AuthContext'
import { ROLE_PROFESSIONAL, ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN } from '../context/roles'
import { useDashboardSummary } from '../hooks/useDashboard'
import { useLedgerSummary } from '../hooks/useLedger'
import { useOutboxStats, useReconciliationSummary } from '../hooks/usePayments'
import { useProfessionalReports, useReportSummary } from '../hooks/useReports'
import { useStoreFeatureFlags } from '../hooks/useStores'
import {
  createDashboardListItemStyle,
  createDashboardPanelStyle
} from '../lib/surfaceStyles'

type Tone = 'neutral' | 'primary' | 'warning' | 'danger' | 'success'

type MetricItem = {
  id: string
  label: string
  value: ReactNode
  detail?: ReactNode
  signal?: string
  icon?: ReactNode
  tone?: Tone
  onSelect?: () => void
}

type ActionItem = {
  id: string
  title: string
  description?: string
  meta?: string
  tone?: Tone
  onSelect?: () => void
}

type AgendaItem = {
  id: string
  time: string
  title: string
  subtitle?: string
  status?: string
  tone?: Tone
}

type RankedItem = {
  id: string
  label: string
  value: ReactNode
  detail?: ReactNode
}

type HealthItem = {
  id: string
  label: string
  value: string
  tone?: Tone
}

type OpportunityItem = {
  id: string
  title: string
  description: string
  tone?: Tone
  actionLabel?: string
  onSelect?: () => void
}

type DashboardHero = {
  title: string
  description: string
  periodLabel: string
  statusLabel: string
  health: HealthItem[]
  quickActions: ActionItem[]
}

type DashboardCopy = {
  metricsTitle: string
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
}

type DashboardOperationCard = {
  title: string
  detail: string
  meta: string
  tone?: Tone
}

type EnterpriseDashboardProps = {
  copy: DashboardCopy
  hero: DashboardHero
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

const currencyFormatter = new Intl.NumberFormat('es-AR', {
  style: 'currency',
  currency: 'ARS',
  maximumFractionDigits: 0
})

const numberFormatter = new Intl.NumberFormat('es-AR', {
  maximumFractionDigits: 0
})

const percentFormatter = new Intl.NumberFormat('es-AR', {
  maximumFractionDigits: 1
})

const copy: DashboardCopy = {
  metricsTitle: 'Resumen del dia',
  operationsTitle: 'Operacion de hoy',
  operationsDescription: 'Turnos, carga operativa y capacidad disponible en una sola vista.',
  actionsTitle: 'Acciones urgentes',
  moneyTitle: 'Dinero',
  performanceTitle: 'Rendimiento semanal',
  alertsTitle: 'Alertas del sistema',
  opportunitiesTitle: 'Oportunidades',
  emptyActions: 'No hay tareas criticas por resolver.',
  emptyAgenda: 'No hay proximos turnos para mostrar.',
  emptyAlerts: 'Sin alertas activas.',
  emptyOpportunities: 'Sin oportunidades destacadas por ahora.'
}

const pageStyle: CSSProperties = {
  display: 'grid',
  gap: 24,
  color: colors2000s.text.primary
}

const metricGridStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'repeat(auto-fit, minmax(184px, 1fr))',
  gap: 16
}

const boardGridStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'minmax(0, 1.9fr) minmax(320px, 1fr)',
  gap: 16,
  alignItems: 'start'
}

const lowerGridStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: 'minmax(0, 1.1fr) minmax(0, 1fr) minmax(0, 0.9fr)',
  gap: 16,
  alignItems: 'start'
}

const panelBodyStyle: CSSProperties = {
  padding: 24
}

const metricPanelStyle: CSSProperties = {
  ...createDashboardPanelStyle(),
  padding: 0
}

const metricPanelBodyStyle: CSSProperties = {
  ...panelBodyStyle,
  display: 'grid',
  gap: 20,
  background: [
    'linear-gradient(135deg, rgba(255, 255, 255, 0.72), rgba(255, 255, 255, 0.48))',
    'radial-gradient(circle at top left, rgba(255, 140, 66, 0.12), transparent 32%)'
  ].join(', ')
}

const subtleTextStyle: CSSProperties = {
  color: colors2000s.text.secondary,
  fontSize: 12,
  lineHeight: '16px',
  fontWeight: 700
}

const headlineStyle: CSSProperties = {
  margin: 0,
  fontSize: 28,
  lineHeight: '32px',
  fontWeight: 900,
  color: colors2000s.text.primary,
  letterSpacing: '-0.02em',
  textTransform: 'uppercase'
}

const emptyStyle: CSSProperties = {
  margin: 0,
  padding: 16,
  borderRadius: 16,
  border: `1px dashed ${colors2000s.border.default}`,
  background: 'rgba(255, 255, 255, 0.45)',
  color: colors2000s.text.secondary,
  fontSize: 12,
  lineHeight: '16px',
  fontWeight: 700
}

const canViewReports = (role: string | undefined, isGlobalAdmin: boolean) =>
  isGlobalAdmin ||
  role === ROLE_STORE_ADMIN ||
  role === ROLE_SUPER_ADMIN ||
  role === ROLE_PROFESSIONAL

const canViewFinancialAdmin = (role: string | undefined, isGlobalAdmin: boolean) =>
  isGlobalAdmin || role === ROLE_STORE_ADMIN || role === ROLE_SUPER_ADMIN

const getAppointmentTone = (status: string): Tone => {
  if (['CANCELLED', 'EXPIRED', 'REJECTED'].includes(status)) return 'danger'
  if (['PENDING', 'PENDING_PAYMENT'].includes(status)) return 'warning'
  if (['CONFIRMED', 'COMPLETED'].includes(status)) return 'success'
  return 'neutral'
}

const toneTokens = (tone: Tone = 'neutral') => {
  if (tone === 'primary') {
    return {
      border: colors2000s.orange.accent,
      accent: colors2000s.orange.accent,
      background: 'rgba(255, 140, 66, 0.12)'
    }
  }
  if (tone === 'success') {
    return {
      border: 'rgba(16, 185, 129, 0.45)',
      accent: '#0f9f6e',
      background: 'rgba(16, 185, 129, 0.1)'
    }
  }
  if (tone === 'warning') {
    return {
      border: 'rgba(245, 158, 11, 0.42)',
      accent: '#b76a00',
      background: 'rgba(245, 158, 11, 0.12)'
    }
  }
  if (tone === 'danger') {
    return {
      border: 'rgba(239, 68, 68, 0.38)',
      accent: '#d13b3b',
      background: 'rgba(239, 68, 68, 0.1)'
    }
  }
  return {
    border: colors2000s.border.light,
    accent: colors2000s.text.secondary,
    background: 'rgba(255, 255, 255, 0.45)'
  }
}

const formatCurrency = (value: number | string | null | undefined) =>
  currencyFormatter.format(Number(value ?? 0))

const formatPercent = (value: number | null | undefined) =>
  `${percentFormatter.format(Number(value ?? 0))}%`

const getTopProfessional = (items: ProfessionalReportItem[] | undefined) =>
  [...(items ?? [])].sort(
    (left, right) => right.occupancy_rate - left.occupancy_rate || right.revenue - left.revenue
  )[0]

const mapAgenda = (appointments: UpcomingAppointment[] | undefined): AgendaItem[] =>
  (appointments ?? []).map((appointment) => ({
    id: appointment.public_id,
    time: format(new Date(appointment.starts_at), 'HH:mm'),
    title: appointment.client_name,
    subtitle: `${appointment.service_name} - ${appointment.staff_name}`,
    status: appointment.status,
    tone: getAppointmentTone(appointment.status)
  }))

const mapTopServices = (items: ReportTopServiceItem[] | undefined): RankedItem[] =>
  (items ?? []).slice(0, 4).map((item) => ({
    id: item.service_id,
    label: item.service_name,
    value: formatCurrency(item.revenue),
    detail: `${numberFormatter.format(item.appointments)} reservas`
  }))

const Dashboard = () => {
  const navigate = useNavigate() as unknown as (path: string) => void
  const { token, user } = useAuth()
  const isGlobalAdmin = Boolean(user?.is_global_admin)
  const reportsAllowed = canViewReports(user?.role, isGlobalAdmin)
  const financialAdminAllowed = canViewFinancialAdmin(user?.role, isGlobalAdmin)
  const fromDate = useMemo(() => format(subDays(new Date(), 7), 'yyyy-MM-dd'), [])
  const toDate = useMemo(() => format(new Date(), 'yyyy-MM-dd'), [])

  const summaryQuery = useDashboardSummary(Boolean(token))
  const featureFlagsQuery = useStoreFeatureFlags()
  const reportsQuery = useReportSummary(fromDate, toDate, reportsAllowed)
  const professionalsQuery = useProfessionalReports(fromDate, toDate, reportsAllowed)

  const flags = featureFlagsQuery.data?.flags
  const paymentsEnabled = Boolean(flags?.payments)
  const ledgerEnabled = Boolean(flags?.ledger)

  const paymentsQuery = useReconciliationSummary(Boolean(paymentsEnabled && financialAdminAllowed))
  const outboxQuery = useOutboxStats(Boolean(paymentsEnabled && financialAdminAllowed))
  const ledgerQuery = useLedgerSummary(Boolean(ledgerEnabled && reportsAllowed))

  const stats = summaryQuery.data?.stats
  const reportStats = reportsQuery.data?.stats
  const clientStats = reportsQuery.data?.client_stats
  const outstandingBalance = Number(
    ledgerQuery.data?.total_balance ?? reportsQuery.data?.debt_summary.outstanding_balance ?? 0
  )
  const debtorsCount = Number(
    ledgerQuery.data?.debtors_count ?? reportsQuery.data?.debt_summary.debtors_count ?? 0
  )
  const topProfessional = getTopProfessional(professionalsQuery.data?.professionals)
  const upcomingAppointments = summaryQuery.data?.upcoming_appointments ?? []
  const occupancy = Number(stats?.occupancy_rate ?? 0)
  const availableCapacity = Math.max(0, 100 - occupancy)
  const paymentErrors =
    Number(outboxQuery.data?.pending_with_error ?? 0) +
    Number(paymentsQuery.data?.failed_webhooks ?? 0)

  const hero = useMemo<DashboardHero>(() => {
    const statusLabel =
      paymentErrors > 0 || Number(stats?.pending_confirmations ?? 0) > 0 || debtorsCount > 0
        ? 'requiere seguimiento'
        : 'estable'

    return {
      title: 'Hoy en Shifty',
      description: `${numberFormatter.format(stats?.appointments_today ?? 0)} turnos, ${numberFormatter.format(
        stats?.pending_confirmations ?? 0
      )} pendientes, ocupacion ${formatPercent(stats?.occupancy_rate)}.`,
      periodLabel: 'Corte operativo: hoy + ultimos 7 dias',
      statusLabel,
      health: [
        {
          id: 'agenda',
          label: 'Agenda',
          value:
            Number(stats?.pending_confirmations ?? 0) > 0
              ? `${numberFormatter.format(stats?.pending_confirmations ?? 0)} pendientes`
              : 'al dia',
          tone: Number(stats?.pending_confirmations ?? 0) > 0 ? 'warning' : 'success'
        },
        {
          id: 'pagos',
          label: 'Cobros online',
          value: !paymentsEnabled
            ? 'deshabilitados'
            : paymentErrors > 0
              ? `${numberFormatter.format(paymentErrors)} errores`
              : 'sin fallas',
          tone: !paymentsEnabled ? 'neutral' : paymentErrors > 0 ? 'danger' : 'success'
        },
        {
          id: 'ledger',
          label: 'Cuentas pendientes',
          value: !ledgerEnabled
            ? 'desactivadas'
            : debtorsCount > 0
              ? `${numberFormatter.format(debtorsCount)} clientes con deuda`
              : 'sin deuda',
          tone: !ledgerEnabled ? 'neutral' : debtorsCount > 0 ? 'warning' : 'success'
        },
        {
          id: 'ingresos',
          label: 'Ingresos',
          value:
            Number(stats?.revenue_trend ?? 0) < 0
              ? `${formatPercent(stats?.revenue_trend)} vs semana pasada`
              : `+${formatPercent(stats?.revenue_trend ?? 0)} de variacion`,
          tone: Number(stats?.revenue_trend ?? 0) < 0 ? 'warning' : 'primary'
        }
      ],
      quickActions: [
        {
          id: 'agenda',
          title: 'Ver agenda',
          description: 'Gestionar turnos y estados',
          tone: 'primary',
          onSelect: () => navigate('/dashboard/calendar')
        },
        {
          id: 'cobros',
          title: 'Registrar cobro',
          description: 'Ir a cobros pendientes del dia',
          tone: 'success',
          onSelect: () => navigate('/dashboard/collections')
        },
        {
          id: 'reportes',
          title: 'Abrir reportes',
          description: 'Revisar tendencia semanal',
          tone: 'neutral',
          onSelect: () => navigate('/dashboard/reports')
        }
      ]
    }
  }, [debtorsCount, ledgerEnabled, navigate, paymentErrors, paymentsEnabled, stats])

  const todayMetrics = useMemo<MetricItem[]>(
    () => [
      {
        id: 'appointments-today',
        label: 'Turnos hoy',
        value: numberFormatter.format(stats?.appointments_today ?? 0),
        detail: `${numberFormatter.format(upcomingAppointments.length)} proximos en agenda`,
        signal: Number(stats?.appointments_today ?? 0) > 0 ? 'Agenda activa' : 'Sin carga',
        icon: <CalendarClock size={18} />,
        tone: 'primary',
        onSelect: () => navigate('/dashboard/calendar')
      },
      {
        id: 'occupancy',
        label: 'Ocupacion',
        value: formatPercent(stats?.occupancy_rate),
        detail: `${formatPercent(availableCapacity)} de capacidad libre`,
        signal:
          occupancy >= 85
            ? 'Dia cargado'
            : availableCapacity >= 40
              ? 'Espacio para crecer'
              : 'Ritmo estable',
        icon: <Gauge size={18} />,
        tone: occupancy >= 85 ? 'warning' : 'neutral',
        onSelect: () => navigate('/dashboard/reports')
      },
      {
        id: 'new-clients',
        label: 'Clientes nuevos',
        value: numberFormatter.format(stats?.new_clients_last_30d ?? 0),
        detail: `${numberFormatter.format(clientStats?.returning_clients ?? 0)} recurrentes activos`,
        signal:
          Number(stats?.new_clients_last_30d ?? 0) > 0
            ? 'Adquisicion en curso'
            : 'Sin altas recientes',
        icon: <UserRoundPlus size={18} />,
        tone: 'success',
        onSelect: () => navigate('/dashboard/users')
      },
      {
        id: 'weekly-revenue',
        label: 'Ingreso semanal',
        value: formatCurrency(stats?.weekly_revenue),
        detail: `${Number(stats?.revenue_trend ?? 0) >= 0 ? '+' : ''}${formatPercent(
          stats?.revenue_trend
        )} vs semana pasada`,
        signal: Number(stats?.revenue_trend ?? 0) >= 0 ? 'Tendencia positiva' : 'Revisar caida',
        icon: <CircleDollarSign size={18} />,
        tone: Number(stats?.revenue_trend ?? 0) < 0 ? 'warning' : 'success',
        onSelect: () => navigate('/dashboard/reports')
      }
    ],
    [
      availableCapacity,
      clientStats?.returning_clients,
      navigate,
      occupancy,
      stats,
      upcomingAppointments.length
    ]
  )

  const operationCards = useMemo<DashboardOperationCard[]>(
    () => [
      {
        title: 'Pendientes por confirmar',
        detail:
          Number(stats?.pending_confirmations ?? 0) > 0
            ? 'Hay reservas esperando decision'
            : 'No hay confirmaciones pendientes',
        meta: numberFormatter.format(stats?.pending_confirmations ?? 0),
        tone: Number(stats?.pending_confirmations ?? 0) > 0 ? 'warning' : 'success'
      },
      {
        title: 'Capacidad disponible',
        detail: 'Espacio operativo libre para hoy',
        meta: formatPercent(availableCapacity),
        tone: availableCapacity < 15 ? 'danger' : availableCapacity < 35 ? 'warning' : 'success'
      },
      {
        title: 'Cancelaciones',
        detail: 'Impacto registrado en el periodo',
        meta: numberFormatter.format(reportStats?.cancelled_appointments ?? 0),
        tone: Number(reportStats?.cancelled_appointments ?? 0) > 0 ? 'warning' : 'neutral'
      },
      {
        title: 'Profesional destacado',
        detail: topProfessional ? topProfessional.staff_name : 'Sin lider claro',
        meta: topProfessional ? formatPercent(topProfessional.occupancy_rate) : '--',
        tone: topProfessional ? 'primary' : 'neutral'
      }
    ],
    [
      availableCapacity,
      reportStats?.cancelled_appointments,
      stats?.pending_confirmations,
      topProfessional
    ]
  )

  const urgentActions = useMemo<ActionItem[]>(() => {
    const items: ActionItem[] = []

    if (Number(stats?.pending_confirmations ?? 0) > 0) {
      items.push({
        id: 'confirmations',
        title: 'Confirmar turnos',
        description: 'Reservas esperando decision',
        meta: numberFormatter.format(stats?.pending_confirmations ?? 0),
        tone: 'warning',
        onSelect: () => navigate('/dashboard/calendar')
      })
    }

    if (Number(paymentsQuery.data?.pending_payments ?? 0) > 0) {
      items.push({
        id: 'pending-payments',
        title: 'Revisar cobros pendientes',
        description: formatCurrency(paymentsQuery.data?.total_pending_amount),
        meta: numberFormatter.format(paymentsQuery.data?.pending_payments ?? 0),
        tone: 'warning',
        onSelect: () => navigate('/dashboard/collections')
      })
    }

    if (paymentErrors > 0) {
      items.push({
        id: 'payment-sync',
        title: 'Revisar cobros online',
        description: 'Hay pagos pendientes de actualizar',
        meta: numberFormatter.format(paymentErrors),
        tone: 'danger',
        onSelect: () => navigate('/dashboard/payments')
      })
    }

    if (debtorsCount > 0) {
      items.push({
        id: 'debtors',
        title: 'Gestionar deuda',
        description: formatCurrency(outstandingBalance),
        meta: numberFormatter.format(debtorsCount),
        tone: 'warning',
        onSelect: () => navigate('/dashboard/ledger')
      })
    }

    return items
  }, [debtorsCount, navigate, outstandingBalance, paymentErrors, paymentsQuery.data, stats])

  const moneyMetrics = useMemo<MetricItem[]>(
    () => [
      {
        id: 'approved-amount',
        label: 'Cobrado',
        value: formatCurrency(
          paymentsQuery.data?.total_approved_amount ?? reportStats?.total_revenue
        ),
        detail: paymentsEnabled ? 'Pagos aprobados y manuales' : 'Ingresos por turnos',
        tone: 'success',
        onSelect: () => navigate(paymentsEnabled ? '/dashboard/collections' : '/dashboard/reports')
      },
      {
        id: 'average-ticket',
        label: 'Ticket promedio',
        value: formatCurrency(reportStats?.average_ticket),
        detail: 'Promedio movil de 7 dias',
        tone: 'neutral',
        onSelect: () => navigate('/dashboard/reports')
      },
      {
        id: 'outstanding-balance',
        label: 'Saldo pendiente',
        value: formatCurrency(outstandingBalance),
        detail: `${numberFormatter.format(debtorsCount)} clientes con deuda`,
        tone: debtorsCount > 0 ? 'warning' : 'neutral',
        onSelect: () => navigate('/dashboard/ledger')
      }
    ],
    [debtorsCount, navigate, outstandingBalance, paymentsEnabled, paymentsQuery.data, reportStats]
  )

  const performanceItems = useMemo<RankedItem[]>(() => {
    const items = mapTopServices(reportsQuery.data?.top_services)

    if (topProfessional) {
      items.unshift({
        id: topProfessional.staff_id,
        label: topProfessional.staff_name,
        value: formatPercent(topProfessional.occupancy_rate),
        detail: `${formatCurrency(topProfessional.revenue)} por profesional`
      })
    }

    if (clientStats) {
      items.push({
        id: 'returning-clients',
        label: 'Clientes recurrentes',
        value: numberFormatter.format(clientStats.returning_clients),
        detail: `${numberFormatter.format(clientStats.new_clients)} nuevos en el periodo`
      })
    }

    return items.slice(0, 5)
  }, [clientStats, reportsQuery.data?.top_services, topProfessional])

  const alerts = useMemo<ActionItem[]>(() => {
    const items: ActionItem[] = []

    if (featureFlagsQuery.isSuccess && !paymentsEnabled) {
      items.push({
        id: 'payments-disabled',
        title: 'Cobros online desactivados',
        description: 'No hay cobro automatico activo',
        tone: 'neutral',
        onSelect: () => navigate('/dashboard/settings')
      })
    }

    if (featureFlagsQuery.isSuccess && !ledgerEnabled) {
      items.push({
        id: 'ledger-disabled',
        title: 'Cuentas pendientes desactivadas',
        description: 'No se lleva la deuda de cada cliente',
        tone: 'neutral',
        onSelect: () => navigate('/dashboard/settings')
      })
    }

    if (Number(reportStats?.cancelled_appointments ?? 0) > 0) {
      items.push({
        id: 'cancellations',
        title: 'Cancelaciones en el periodo',
        description: 'Revisar patron por servicio o profesional',
        meta: numberFormatter.format(reportStats?.cancelled_appointments ?? 0),
        tone: 'warning',
        onSelect: () => navigate('/dashboard/reports')
      })
    }

    if (Number(stats?.revenue_trend ?? 0) < -15) {
      items.push({
        id: 'revenue-drop',
        title: 'Ingreso semanal en baja',
        description: `${formatPercent(stats?.revenue_trend)} contra la semana anterior`,
        tone: 'danger',
        onSelect: () => navigate('/dashboard/reports')
      })
    }

    return items
  }, [featureFlagsQuery.isSuccess, ledgerEnabled, navigate, paymentsEnabled, reportStats, stats])

  const opportunities = useMemo<OpportunityItem[]>(() => {
    const items: OpportunityItem[] = []

    if (availableCapacity >= 35) {
      items.push({
        id: 'low-occupancy',
        title: 'Dia con capacidad libre',
        description: `Queda ${formatPercent(availableCapacity)} sin ocupar. Conviene reforzar agenda o activar promociones.`,
        tone: 'primary',
        actionLabel: 'Ver agenda',
        onSelect: () => navigate('/dashboard/calendar')
      })
    }

    if (topProfessional && topProfessional.occupancy_rate >= 70) {
      items.push({
        id: 'top-professional',
        title: 'Hay una referencia clara para replicar',
        description: `${topProfessional.staff_name} lidera con ${formatPercent(
          topProfessional.occupancy_rate
        )}. Sirve como benchmark interno.`,
        tone: 'success',
        actionLabel: 'Ver rendimiento',
        onSelect: () => navigate('/dashboard/reports')
      })
    }

    if (clientStats && clientStats.new_clients > 0) {
      items.push({
        id: 'client-growth',
        title: 'Base de clientes en movimiento',
        description: `${numberFormatter.format(
          clientStats.new_clients
        )} clientes nuevos ingresaron al periodo. Conviene trabajar recurrencia y rebook.`,
        tone: 'warning',
        actionLabel: 'Abrir usuarios',
        onSelect: () => navigate('/dashboard/users')
      })
    }

    return items.slice(0, 3)
  }, [availableCapacity, clientStats, navigate, topProfessional])

  return (
    <EnterpriseDashboard
      copy={copy}
      hero={hero}
      todayMetrics={todayMetrics}
      urgentActions={urgentActions}
      agenda={mapAgenda(upcomingAppointments)}
      operationCards={operationCards}
      moneyMetrics={moneyMetrics}
      performanceItems={performanceItems}
      alerts={alerts}
      opportunities={opportunities}
      isLoading={summaryQuery.isLoading}
      errorMessage={summaryQuery.isError ? 'No se pudo cargar el resumen operativo.' : undefined}
    />
  )
}

function EnterpriseDashboard({
  copy,
  hero,
  todayMetrics,
  urgentActions,
  agenda,
  operationCards,
  moneyMetrics,
  performanceItems,
  alerts,
  opportunities,
  isLoading,
  errorMessage
}: EnterpriseDashboardProps) {
  if (isLoading) {
    return (
      <main style={pageStyle}>
        <div
          style={{
            ...createDashboardPanelStyle(),
            ...panelBodyStyle,
            color: colors2000s.text.secondary,
            fontWeight: 700
          }}
        >
          Cargando dashboard...
        </div>
      </main>
    )
  }

  return (
    <main style={pageStyle}>
      {errorMessage ? <ErrorPanel message={errorMessage} /> : null}

      <HeroPanel hero={hero} />

      <SummaryMetricsPanel title={copy.metricsTitle} metrics={todayMetrics} />

      <section style={boardGridStyle} className="dashboard-board-grid">
        <OperationPanel
          title={copy.operationsTitle}
          description={copy.operationsDescription}
          agenda={agenda}
          cards={operationCards}
        />

        <div style={{ display: 'grid', gap: 16 }}>
          <Panel
            title={copy.actionsTitle}
            description="Lo que merece atencion inmediata."
            icon={<CircleAlert size={18} />}
          >
            <ActionList items={urgentActions} emptyText={copy.emptyActions} />
          </Panel>

          <Panel
            title={copy.moneyTitle}
            description="Cobros, ticket y deuda actual."
            icon={<Wallet size={18} />}
          >
            <MetricStack items={moneyMetrics} />
          </Panel>
        </div>
      </section>

      <section style={lowerGridStyle} className="dashboard-lower-grid">
        <Panel
          title={copy.performanceTitle}
          description="Servicios, profesionales y recurrencia."
          icon={<TrendingUp size={18} />}
        >
          <RankedList items={performanceItems} />
        </Panel>

        <Panel
          title={copy.alertsTitle}
          description="Desvios, caidas y modulos fuera de regimen."
          icon={<CircleAlert size={18} />}
        >
          <ActionList items={alerts} emptyText={copy.emptyAlerts} compact />
        </Panel>

        <Panel
          title={copy.opportunitiesTitle}
          description="Espacios para crecer o corregir rapido."
          icon={<Sparkles size={18} />}
        >
          <OpportunityList items={opportunities} emptyText={copy.emptyOpportunities} />
        </Panel>
      </section>

      <style>
        {`
          @media (max-width: 1200px) {
            .dashboard-board-grid,
            .dashboard-lower-grid {
              grid-template-columns: 1fr !important;
            }
          }
        `}
      </style>
    </main>
  )
}

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
              border: `1px solid ${colors2000s.border.default}`,
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
              border: `1px solid ${colors2000s.border.default}`,
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
            borderRadius: 12,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            background: 'rgba(255, 140, 66, 0.12)',
            border: `1px solid rgba(200, 90, 15, 0.25)`,
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

function OperationPanel({
  title,
  description,
  agenda,
  cards
}: {
  title: string
  description: string
  agenda: AgendaItem[]
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
                borderRadius: 16,
                background: 'rgba(255, 255, 255, 0.72)',
                border: `1px solid ${colors2000s.border.light}`,
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

            <AgendaList items={agenda} emptyText={copy.emptyAgenda} />
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

function MetricCard({ item, emphasis = false }: { item: MetricItem; emphasis?: boolean }) {
  const tone = toneTokens(item.tone)

  return (
    <button
      type="button"
      onClick={item.onSelect}
      style={{
        display: 'grid',
        gap: emphasis ? 12 : 8,
        minHeight: emphasis ? 164 : 112,
        padding: emphasis ? 18 : 16,
        background: emphasis
          ? [
              'linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(255, 255, 255, 0.82))',
              tone.background
            ].join(', ')
          : 'rgba(255, 255, 255, 0.65)',
        border: `1px solid ${tone.border}`,
        borderRadius: 20,
        boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
        color: colors2000s.text.primary,
        textAlign: 'left',
        cursor: item.onSelect ? 'pointer' : 'default',
        position: 'relative'
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'flex-start',
          justifyContent: 'space-between',
          gap: 10
        }}
      >
        <div style={{ display: 'grid', gap: 8 }}>
          <span style={{ ...subtleTextStyle, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            {item.label}
          </span>
          {item.signal ? (
            <span
              style={{
                alignSelf: 'start',
                padding: '4px 8px',
                borderRadius: 999,
                border: `1px solid ${tone.border}`,
                background: 'rgba(255, 255, 255, 0.74)',
                color: tone.accent,
                fontSize: 10,
                lineHeight: '12px',
                fontWeight: 900,
                textTransform: 'uppercase',
                letterSpacing: '0.08em'
              }}
            >
              {item.signal}
            </span>
          ) : null}
        </div>

        {item.icon ? (
          <span
            style={{
              width: emphasis ? 40 : 34,
              height: emphasis ? 40 : 34,
              borderRadius: 14,
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              background: 'rgba(255, 255, 255, 0.86)',
              border: `1px solid ${tone.border}`,
              color: tone.accent,
              boxShadow: colors2000s.shadows.insetLight,
              flexShrink: 0
            }}
          >
            {item.icon}
          </span>
        ) : null}
      </div>
      <strong
        style={{
          color: item.tone === 'primary' ? colors2000s.orange.accent : colors2000s.text.primary,
          fontSize: emphasis ? 32 : 26,
          lineHeight: emphasis ? '36px' : '30px',
          fontWeight: 900,
          letterSpacing: '-0.03em'
        }}
      >
        {item.value}
      </strong>
      {item.detail ? (
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 10,
            marginTop: 'auto',
            paddingTop: emphasis ? 8 : 0,
            borderTop: emphasis ? `1px solid ${tone.border}` : 'none'
          }}
        >
          <span style={{ color: tone.accent, fontSize: 12, lineHeight: '16px', fontWeight: 800 }}>
            {item.detail}
          </span>
          {emphasis ? <ArrowUpRight size={14} color={tone.accent} /> : null}
        </div>
      ) : null}
    </button>
  )
}

function MetricStack({ items }: { items: MetricItem[] }) {
  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {items.map((item) => (
        <MetricCard key={item.id} item={item} />
      ))}
    </div>
  )
}

function HealthPill({ item }: { item: HealthItem }) {
  const tone = toneTokens(item.tone)

  return (
    <div
      style={{
        padding: '14px 16px',
        borderRadius: 18,
        border: `1px solid ${tone.border}`,
        background: tone.background,
        boxShadow: colors2000s.shadows.insetLight,
        display: 'grid',
        gap: 4
      }}
    >
      <span style={{ ...subtleTextStyle, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        {item.label}
      </span>
      <strong style={{ color: tone.accent, fontSize: 14, lineHeight: '18px', fontWeight: 900 }}>
        {item.value}
      </strong>
    </div>
  )
}

function QuickActionCard({ item }: { item: ActionItem }) {
  const tone = toneTokens(item.tone)

  return (
    <button
      type="button"
      onClick={item.onSelect}
      style={{
        ...buttonStyles2000s.default,
        borderRadius: 20,
        padding: 16,
        textAlign: 'left',
        display: 'grid',
        gap: 6,
        borderColor: tone.border
      }}
    >
      <strong
        style={{
          color: colors2000s.text.primary,
          fontSize: 14,
          lineHeight: '18px',
          fontWeight: 900
        }}
      >
        {item.title}
      </strong>
      {item.description ? (
        <span
          style={{
            color: colors2000s.text.secondary,
            fontSize: 12,
            lineHeight: '16px',
            fontWeight: 700
          }}
        >
          {item.description}
        </span>
      ) : null}
    </button>
  )
}

function ActionList({
  items,
  emptyText,
  compact = false
}: {
  items: ActionItem[]
  emptyText: string
  compact?: boolean
}) {
  if (!items.length) return <EmptyState text={emptyText} />

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {items.map((item) => {
        const tone = toneTokens(item.tone)
        return (
          <button
            key={item.id}
            type="button"
            onClick={item.onSelect}
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 16,
              minHeight: compact ? 64 : 72,
              ...createDashboardListItemStyle(tone.border, tone.background, compact ? 14 : 16),
              color: colors2000s.text.primary,
              cursor: item.onSelect ? 'pointer' : 'default',
              textAlign: 'left'
            }}
          >
            <span style={{ display: 'grid', gap: 4, minWidth: 0 }}>
              <strong style={{ fontSize: 14, lineHeight: '18px', fontWeight: 900 }}>
                {item.title}
              </strong>
              {item.description ? (
                <small
                  style={{
                    color: colors2000s.text.secondary,
                    fontSize: 12,
                    lineHeight: '16px',
                    fontWeight: 700
                  }}
                >
                  {item.description}
                </small>
              ) : null}
            </span>
            {item.meta ? (
              <em
                style={{
                  color: tone.accent,
                  fontSize: 12,
                  lineHeight: '16px',
                  fontStyle: 'normal',
                  whiteSpace: 'nowrap',
                  fontWeight: 900
                }}
              >
                {item.meta}
              </em>
            ) : null}
          </button>
        )
      })}
    </div>
  )
}

function AgendaList({ items, emptyText }: { items: AgendaItem[]; emptyText: string }) {
  if (!items.length) return <EmptyState text={emptyText} />

  return (
    <div style={{ display: 'grid', gap: 10 }}>
      {items.map((item) => {
        const tone = toneTokens(item.tone)

        return (
          <div
            key={item.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 16,
              minHeight: 74,
              ...createDashboardListItemStyle(tone.border, 'rgba(255, 255, 255, 0.68)', 14)
            }}
          >
            <div
              style={{
                width: 60,
                alignSelf: 'stretch',
                borderRadius: 14,
                display: 'grid',
                placeItems: 'center',
                background: tone.background,
                border: `1px solid ${tone.border}`
              }}
            >
              <time
                style={{ color: tone.accent, fontSize: 14, lineHeight: '18px', fontWeight: 900 }}
              >
                {item.time}
              </time>
            </div>

            <span style={{ display: 'grid', gap: 4, minWidth: 0, flex: 1 }}>
              <strong style={{ fontSize: 14, lineHeight: '18px', fontWeight: 900 }}>
                {item.title}
              </strong>
              {item.subtitle ? (
                <small
                  style={{
                    color: colors2000s.text.secondary,
                    fontSize: 12,
                    lineHeight: '16px',
                    fontWeight: 700
                  }}
                >
                  {item.subtitle}
                </small>
              ) : null}
            </span>

            {item.status ? (
              <span
                style={{
                  padding: '6px 10px',
                  borderRadius: 999,
                  background: tone.background,
                  border: `1px solid ${tone.border}`,
                  color: tone.accent,
                  fontSize: 10,
                  lineHeight: '12px',
                  fontWeight: 900,
                  letterSpacing: '0.08em',
                  textTransform: 'uppercase',
                  whiteSpace: 'nowrap'
                }}
              >
                {item.status}
              </span>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

function DashboardSignalCard({ card }: { card: DashboardOperationCard }) {
  const tone = toneTokens(card.tone)

  return (
    <div
      style={{
        ...createDashboardListItemStyle(tone.border, tone.background),
        display: 'grid',
        gap: 8
      }}
    >
      <span style={{ ...subtleTextStyle, textTransform: 'uppercase', letterSpacing: '0.08em' }}>
        {card.title}
      </span>
      <strong style={{ color: tone.accent, fontSize: 22, lineHeight: '26px', fontWeight: 900 }}>
        {card.meta}
      </strong>
      <p
        style={{
          margin: 0,
          color: colors2000s.text.secondary,
          fontSize: 12,
          lineHeight: '16px',
          fontWeight: 700
        }}
      >
        {card.detail}
      </p>
    </div>
  )
}

function RankedList({ items }: { items: RankedItem[] }) {
  if (!items.length) return <EmptyState text="Sin datos para este periodo." />

  return (
    <ol style={{ display: 'grid', gap: 12, listStyle: 'none', margin: 0, padding: 0 }}>
      {items.map((item, index) => (
          <li
            key={item.id}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              gap: 14,
              minHeight: 70,
              ...createDashboardListItemStyle(colors2000s.border.light, 'rgba(255, 255, 255, 0.65)', 14)
            }}
          >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
            <span
              style={{
                width: 34,
                height: 34,
                borderRadius: 12,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'rgba(255, 140, 66, 0.12)',
                border: `1px solid rgba(200, 90, 15, 0.18)`,
                color: colors2000s.orange.accent,
                fontSize: 12,
                lineHeight: '16px',
                fontWeight: 900
              }}
            >
              {index + 1}
            </span>
            <span style={{ display: 'grid', gap: 4, minWidth: 0 }}>
              <strong style={{ fontSize: 14, lineHeight: '18px', fontWeight: 900 }}>
                {item.label}
              </strong>
              {item.detail ? (
                <small
                  style={{
                    color: colors2000s.text.secondary,
                    fontSize: 12,
                    lineHeight: '16px',
                    fontWeight: 700
                  }}
                >
                  {item.detail}
                </small>
              ) : null}
            </span>
          </div>
          <em
            style={{
              color: colors2000s.orange.accent,
              fontSize: 12,
              lineHeight: '16px',
              fontStyle: 'normal',
              whiteSpace: 'nowrap',
              fontWeight: 900
            }}
          >
            {item.value}
          </em>
        </li>
      ))}
    </ol>
  )
}

function OpportunityList({ items, emptyText }: { items: OpportunityItem[]; emptyText: string }) {
  if (!items.length) return <EmptyState text={emptyText} />

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {items.map((item) => {
        const tone = toneTokens(item.tone)
        return (
          <div
            key={item.id}
            style={{
              ...createDashboardListItemStyle(tone.border, 'rgba(255, 255, 255, 0.62)', 16),
              display: 'grid',
              gap: 10
            }}
          >
            <div style={{ display: 'grid', gap: 4 }}>
              <strong
                style={{
                  color: colors2000s.text.primary,
                  fontSize: 14,
                  lineHeight: '18px',
                  fontWeight: 900
                }}
              >
                {item.title}
              </strong>
              <p
                style={{
                  margin: 0,
                  color: colors2000s.text.secondary,
                  fontSize: 12,
                  lineHeight: '16px',
                  fontWeight: 700
                }}
              >
                {item.description}
              </p>
            </div>

            {item.actionLabel && item.onSelect ? (
              <button
                type="button"
                onClick={item.onSelect}
                style={{
                  ...buttonStyles2000s.default,
                  borderRadius: 14,
                  padding: '10px 12px',
                  justifySelf: 'start',
                  fontSize: 11,
                  lineHeight: '14px',
                  fontWeight: 900,
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em',
                  color: tone.accent
                }}
              >
                {item.actionLabel}
              </button>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

function EmptyState({ text }: { text: string }) {
  return <p style={emptyStyle}>{text}</p>
}

export default Dashboard
