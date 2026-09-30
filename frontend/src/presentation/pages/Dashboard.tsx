import { lazy, Suspense, useMemo } from 'react'

import { subDays } from 'date-fns'
import {
  CalendarClock,
  CalendarX,
  Clock3,
  DollarSign,
  Gauge,
  LayoutDashboard,
  ListChecks,
  Sparkles,
  TrendingUp,
  TriangleAlert,
  UserRoundPlus,
  Wallet
} from 'lucide-react'
import { useNavigate } from 'react-router'

import { isBookingStatus, type BookingStatusValue } from '@domain/value-objects/BookingStatus'

import type { UpcomingAppointment } from '@application/services/DashboardService'
import type {
  ProfessionalReportItem,
  ReportAppointmentItem,
  ReportTopServiceItem
} from '@application/services/ReportsService'

import {
  formatArgentinaDate,
  formatArgentinaDayMonth,
  formatArgentinaTime
} from '@shared/utils/argentinaTime'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import DashboardSignalCard from '../components/organisms/dashboard/DashboardSignalCard'
import {
  boardGridStyle,
  emptyStyle,
  headlineStyle,
  insightsGridStyle,
  lowerGridStyle,
  metricGridStyle,
  metricPanelBodyStyle,
  metricPanelStyle,
  pageStyle,
  panelBodyStyle,
  subtleTextStyle
} from '../components/organisms/dashboard/dashboardStyles'
import EmptyState from '../components/organisms/dashboard/EmptyState'
import ErrorPanel from '../components/organisms/dashboard/ErrorPanel'
import HealthPill from '../components/organisms/dashboard/HealthPill'
import MetricCard from '../components/organisms/dashboard/MetricCard'
import MetricStack from '../components/organisms/dashboard/MetricStack'
import Panel from '../components/organisms/dashboard/Panel'
import QuickActionCard from '../components/organisms/dashboard/QuickActionCard'
import SectionHeader from '../components/organisms/dashboard/SectionHeader'
import { toneTokens } from '../components/organisms/dashboard/toneTokens'
import type {
  ActionItem,
  AgendaItem,
  DashboardCopy,
  DashboardHero,
  DashboardOperationCard,
  EnterpriseDashboardProps,
  MetricItem,
  OpportunityItem,
  RankedItem,
  Tone,
  TransactionItem
} from '../components/organisms/dashboard/types'
import { useAuth } from '../context/AuthContext'
import { ROLE_PROFESSIONAL, ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN } from '../context/roles'
import { useDashboardSummary } from '../hooks/useDashboard'
import { useLedgerSummary } from '../hooks/useLedger'
import { useOutboxStats, useReconciliationSummary } from '../hooks/usePayments'
import { useProfessionalReports, useReportSummary, useReportTrend } from '../hooks/useReports'
import { useStoreFeatureFlags } from '../hooks/useStores'
import { currencyFmtEsAr } from '../lib/formatters'
import { createDashboardListItemStyle, createDashboardPanelStyle } from '../lib/surfaceStyles'

// Los graficos traen recharts, que era casi todo el chunk del Dashboard
// (426 KB) y bajaba en la primera pantalla del dueno. Con lazy van a su propio
// chunk y la pagina pinta sin esperarlo (F4-13).
const TrendChart = lazy(() => import('../components/organisms/dashboard/TrendChart'))
const SalesDonut = lazy(() => import('../components/organisms/dashboard/SalesDonut'))

// Alto del area de dibujo de cada grafico (el `height` de su contenedor en
// TrendChart.tsx y SalesDonut.tsx). No se importa de esos modulos: hacerlo
// traeria recharts de vuelta al chunk del Dashboard.
const TREND_CHART_HEIGHT = 280
const SALES_DONUT_HEIGHT = 200

const numberFormatter = new Intl.NumberFormat('es-AR', {
  maximumFractionDigits: 0
})

const percentFormatter = new Intl.NumberFormat('es-AR', {
  maximumFractionDigits: 1
})

const copy: DashboardCopy = {
  metricsTitle: 'Resumen del dia',
  transactionsTitle: 'Transacciones',
  transactionsDescription: 'Ultimos turnos del periodo con su estado y monto.',
  viewTransactionsLabel: 'Ver todas',
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
  emptyOpportunities: 'Sin oportunidades destacadas por ahora.',
  emptyTransactions: 'No hay turnos registrados en el periodo.'
}

const canViewReports = (role: string | undefined, isGlobalAdmin: boolean) =>
  isGlobalAdmin ||
  role === ROLE_STORE_ADMIN ||
  role === ROLE_SUPER_ADMIN ||
  role === ROLE_PROFESSIONAL

const canViewFinancialAdmin = (role: string | undefined, isGlobalAdmin: boolean) =>
  isGlobalAdmin || role === ROLE_STORE_ADMIN || role === ROLE_SUPER_ADMIN

/**
 * La API manda los estados en minusculas (`appointments/model.py`); esto los
 * comparaba en MAYUSCULAS, asi que las tres ramas eran codigo muerto y todo
 * caia en 'neutral': un turno cancelado se pintaba igual que uno confirmado.
 *
 * El mapa completo reemplaza a los tres `includes`: si el backend agrega un
 * estado, `BookingStatusValue` cambia y esto deja de compilar, en vez de
 * volver al gris en silencio. `'REJECTED'` no existia en el enum, y `absent`
 * no estaba en ninguna de las tres listas.
 */
const APPOINTMENT_TONES: Record<BookingStatusValue, Tone> = {
  pending: 'warning',
  pending_payment: 'warning',
  confirmed: 'success',
  completed: 'success',
  cancelled: 'danger',
  absent: 'danger',
  expired: 'danger'
}

const getAppointmentTone = (status: string): Tone =>
  isBookingStatus(status) ? APPOINTMENT_TONES[status] : 'neutral'

const formatCurrency = (value: number | string | null | undefined) =>
  currencyFmtEsAr.format(Number(value ?? 0))

const formatPercent = (value: number | null | undefined) =>
  `${percentFormatter.format(Number(value ?? 0))}%`

const getTopProfessional = (items: ProfessionalReportItem[] | undefined) =>
  [...(items ?? [])].sort(
    (left, right) => right.occupancy_rate - left.occupancy_rate || right.revenue - left.revenue
  )[0]

const mapAgenda = (appointments: UpcomingAppointment[] | undefined): AgendaItem[] =>
  (appointments ?? []).map((appointment) => ({
    id: appointment.public_id,
    time: formatArgentinaTime(appointment.starts_at),
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

const mapTransactions = (items: ReportAppointmentItem[] | undefined): TransactionItem[] =>
  [...(items ?? [])]
    .sort((left, right) => new Date(right.starts_at).getTime() - new Date(left.starts_at).getTime())
    .slice(0, 6)
    .map((item) => ({
      id: item.public_id,
      title: item.client_name,
      subtitle: `${item.service_name} - ${formatArgentinaDayMonth(item.starts_at)} ${formatArgentinaTime(item.starts_at)}`,
      amount: formatCurrency(item.service_price),
      status: item.status,
      tone: getAppointmentTone(item.status)
    }))

const Dashboard = () => {
  const navigate = useNavigate()
  const { token, user } = useAuth()
  const isGlobalAdmin = Boolean(user?.is_global_admin)
  const reportsAllowed = canViewReports(user?.role, isGlobalAdmin)
  const financialAdminAllowed = canViewFinancialAdmin(user?.role, isGlobalAdmin)
  // El rango del reporte es un dia de negocio argentino: con `format` de
  // date-fns, un navegador en otra zona pedia el dia equivocado. El useMemo con
  // [] no es defensivo: congela el rango (parte de la query key) mientras la
  // pagina esta montada, en vez de moverlo solo al cruzar la medianoche.
  const fromDate = useMemo(() => formatArgentinaDate(subDays(new Date(), 7).toISOString()), [])
  const toDate = useMemo(() => formatArgentinaDate(new Date().toISOString()), [])

  const summaryQuery = useDashboardSummary(Boolean(token))
  const featureFlagsQuery = useStoreFeatureFlags()
  const reportsQuery = useReportSummary(fromDate, toDate, reportsAllowed)
  const professionalsQuery = useProfessionalReports(fromDate, toDate, reportsAllowed)
  const trendQuery = useReportTrend(6, reportsAllowed)

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

  const heroStatusLabel =
    paymentErrors > 0 || Number(stats?.pending_confirmations ?? 0) > 0 || debtorsCount > 0
      ? 'requiere seguimiento'
      : 'estable'

  const hero: DashboardHero = {
    title: 'Hoy en Shifty',
    description: `${numberFormatter.format(stats?.appointments_today ?? 0)} turnos, ${numberFormatter.format(
      stats?.pending_confirmations ?? 0
    )} pendientes, ocupacion ${formatPercent(stats?.occupancy_rate)}.`,
    periodLabel: 'Corte operativo: hoy + ultimos 7 dias',
    statusLabel: heroStatusLabel,
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
        onSelect: () => void navigate('/dashboard/calendar')
      },
      {
        id: 'cobros',
        title: 'Registrar cobro',
        description: 'Ir a cobros pendientes del dia',
        tone: 'success',
        onSelect: () => void navigate('/dashboard/collections')
      },
      {
        id: 'reportes',
        title: 'Abrir reportes',
        description: 'Revisar tendencia semanal',
        tone: 'neutral',
        onSelect: () => void navigate('/dashboard/reports')
      }
    ]
  }

  const todayMetrics: MetricItem[] = [
    {
      id: 'weekly-revenue',
      label: 'Ingreso semanal',
      value: formatCurrency(stats?.weekly_revenue),
      detail: `${Number(stats?.revenue_trend ?? 0) >= 0 ? '+' : ''}${formatPercent(
        stats?.revenue_trend
      )} vs semana pasada`,
      signal: Number(stats?.revenue_trend ?? 0) >= 0 ? 'Tendencia positiva' : 'Revisar caida',
      icon: <DollarSign size={18} />,
      tone: Number(stats?.revenue_trend ?? 0) < 0 ? 'warning' : 'success',
      onSelect: () => void navigate('/dashboard/reports')
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
      onSelect: () => void navigate('/dashboard/users')
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
      onSelect: () => void navigate('/dashboard/reports')
    },
    {
      id: 'cancellations',
      label: 'Cancelaciones',
      value: numberFormatter.format(reportStats?.cancelled_appointments ?? 0),
      detail: `${numberFormatter.format(upcomingAppointments.length)} proximos en agenda`,
      signal:
        Number(reportStats?.cancelled_appointments ?? 0) > 0
          ? 'Revisar patron'
          : 'Sin cancelaciones',
      icon: <CalendarX size={18} />,
      tone: Number(reportStats?.cancelled_appointments ?? 0) > 0 ? 'warning' : 'success',
      onSelect: () => void navigate('/dashboard/reports')
    }
  ]

  const operationCards: DashboardOperationCard[] = [
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
  ]

  const urgentActions: ActionItem[] = []

  if (Number(stats?.pending_confirmations ?? 0) > 0) {
    urgentActions.push({
      id: 'confirmations',
      title: 'Confirmar turnos',
      description: 'Reservas esperando decision',
      meta: numberFormatter.format(stats?.pending_confirmations ?? 0),
      tone: 'warning',
      onSelect: () => void navigate('/dashboard/calendar')
    })
  }

  if (Number(paymentsQuery.data?.pending_payments ?? 0) > 0) {
    urgentActions.push({
      id: 'pending-payments',
      title: 'Revisar cobros pendientes',
      description: formatCurrency(paymentsQuery.data?.total_pending_amount),
      meta: numberFormatter.format(paymentsQuery.data?.pending_payments ?? 0),
      tone: 'warning',
      onSelect: () => void navigate('/dashboard/collections')
    })
  }

  if (paymentErrors > 0) {
    urgentActions.push({
      id: 'payment-sync',
      title: 'Revisar cobros online',
      description: 'Hay pagos pendientes de actualizar',
      meta: numberFormatter.format(paymentErrors),
      tone: 'danger',
      onSelect: () => void navigate('/dashboard/payments')
    })
  }

  if (debtorsCount > 0) {
    urgentActions.push({
      id: 'debtors',
      title: 'Gestionar deuda',
      description: formatCurrency(outstandingBalance),
      meta: numberFormatter.format(debtorsCount),
      tone: 'warning',
      onSelect: () => void navigate('/dashboard/ledger')
    })
  }

  const moneyMetrics: MetricItem[] = [
    {
      id: 'approved-amount',
      label: 'Cobrado',
      value: formatCurrency(
        paymentsQuery.data?.total_approved_amount ?? reportStats?.total_revenue
      ),
      detail: paymentsEnabled ? 'Pagos aprobados y manuales' : 'Ingresos por turnos',
      tone: 'success',
      onSelect: () =>
        void navigate(paymentsEnabled ? '/dashboard/collections' : '/dashboard/reports')
    },
    {
      id: 'average-ticket',
      label: 'Ticket promedio',
      value: formatCurrency(reportStats?.average_ticket),
      detail: 'Promedio movil de 7 dias',
      tone: 'neutral',
      onSelect: () => void navigate('/dashboard/reports')
    },
    {
      id: 'outstanding-balance',
      label: 'Saldo pendiente',
      value: formatCurrency(outstandingBalance),
      detail: `${numberFormatter.format(debtorsCount)} clientes con deuda`,
      tone: debtorsCount > 0 ? 'warning' : 'neutral',
      onSelect: () => void navigate('/dashboard/ledger')
    }
  ]

  const rankedItems: RankedItem[] = mapTopServices(reportsQuery.data?.top_services)

  if (topProfessional) {
    rankedItems.unshift({
      id: topProfessional.staff_id,
      label: topProfessional.staff_name,
      value: formatPercent(topProfessional.occupancy_rate),
      detail: `${formatCurrency(topProfessional.revenue)} por profesional`
    })
  }

  if (clientStats) {
    rankedItems.push({
      id: 'returning-clients',
      label: 'Clientes recurrentes',
      value: numberFormatter.format(clientStats.returning_clients),
      detail: `${numberFormatter.format(clientStats.new_clients)} nuevos en el periodo`
    })
  }

  const performanceItems = rankedItems.slice(0, 5)

  const alerts: ActionItem[] = []

  if (featureFlagsQuery.isSuccess && !paymentsEnabled) {
    alerts.push({
      id: 'payments-disabled',
      title: 'Cobros online desactivados',
      description: 'No hay cobro automatico activo',
      tone: 'neutral',
      onSelect: () => void navigate('/dashboard/settings')
    })
  }

  if (featureFlagsQuery.isSuccess && !ledgerEnabled) {
    alerts.push({
      id: 'ledger-disabled',
      title: 'Cuentas pendientes desactivadas',
      description: 'No se lleva la deuda de cada cliente',
      tone: 'neutral',
      onSelect: () => void navigate('/dashboard/settings')
    })
  }

  if (Number(reportStats?.cancelled_appointments ?? 0) > 0) {
    alerts.push({
      id: 'cancellations',
      title: 'Cancelaciones en el periodo',
      description: 'Revisar patron por servicio o profesional',
      meta: numberFormatter.format(reportStats?.cancelled_appointments ?? 0),
      tone: 'warning',
      onSelect: () => void navigate('/dashboard/reports')
    })
  }

  if (Number(stats?.revenue_trend ?? 0) < -15) {
    alerts.push({
      id: 'revenue-drop',
      title: 'Ingreso semanal en baja',
      description: `${formatPercent(stats?.revenue_trend)} contra la semana anterior`,
      tone: 'danger',
      onSelect: () => void navigate('/dashboard/reports')
    })
  }

  const opportunityCandidates: OpportunityItem[] = []

  if (availableCapacity >= 35) {
    opportunityCandidates.push({
      id: 'low-occupancy',
      title: 'Dia con capacidad libre',
      description: `Queda ${formatPercent(availableCapacity)} sin ocupar. Conviene reforzar agenda o activar promociones.`,
      tone: 'primary',
      actionLabel: 'Ver agenda',
      onSelect: () => void navigate('/dashboard/calendar')
    })
  }

  if (topProfessional && topProfessional.occupancy_rate >= 70) {
    opportunityCandidates.push({
      id: 'top-professional',
      title: 'Hay una referencia clara para replicar',
      description: `${topProfessional.staff_name} lidera con ${formatPercent(
        topProfessional.occupancy_rate
      )}. Sirve como benchmark interno.`,
      tone: 'success',
      actionLabel: 'Ver rendimiento',
      onSelect: () => void navigate('/dashboard/reports')
    })
  }

  if (clientStats && clientStats.new_clients > 0) {
    opportunityCandidates.push({
      id: 'client-growth',
      title: 'Base de clientes en movimiento',
      description: `${numberFormatter.format(
        clientStats.new_clients
      )} clientes nuevos ingresaron al periodo. Conviene trabajar recurrencia y rebook.`,
      tone: 'warning',
      actionLabel: 'Abrir usuarios',
      onSelect: () => void navigate('/dashboard/users')
    })
  }

  const opportunities = opportunityCandidates.slice(0, 3)

  return (
    <EnterpriseDashboard
      copy={copy}
      hero={hero}
      trendPoints={trendQuery.data?.points ?? []}
      trendLoading={trendQuery.isLoading}
      topServices={reportsQuery.data?.top_services ?? []}
      salesLoading={reportsQuery.isLoading}
      transactions={mapTransactions(reportsQuery.data?.appointments)}
      onViewTransactions={() => void navigate('/dashboard/reports')}
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
  trendPoints,
  trendLoading,
  topServices,
  salesLoading,
  transactions,
  onViewTransactions,
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

      <SummaryMetricsPanel title={copy.metricsTitle} metrics={todayMetrics} />

      <section style={insightsGridStyle} className="dashboard-insights-grid">
        <Suspense
          fallback={<ChartPlaceholder text="Cargando tendencia..." height={TREND_CHART_HEIGHT} />}
        >
          <TrendChart points={trendPoints} isLoading={trendLoading} />
        </Suspense>
        <Suspense
          fallback={<ChartPlaceholder text="Cargando ventas..." height={SALES_DONUT_HEIGHT} />}
        >
          <SalesDonut services={topServices} isLoading={salesLoading} />
        </Suspense>
        <TransactionsPanel
          title={copy.transactionsTitle}
          description={copy.transactionsDescription}
          items={transactions}
          emptyText={copy.emptyTransactions}
          viewAllLabel={copy.viewTransactionsLabel}
          onViewAll={onViewTransactions}
        />
      </section>

      <HeroPanel hero={hero} />

      <section style={boardGridStyle} className="dashboard-board-grid">
        <OperationPanel
          title={copy.operationsTitle}
          description={copy.operationsDescription}
          agenda={agenda}
          emptyAgendaText={copy.emptyAgenda}
          cards={operationCards}
        />

        <div style={{ display: 'grid', gap: 16 }}>
          <Panel
            title={copy.actionsTitle}
            description="Lo que merece atencion inmediata."
            icon={<TriangleAlert size={18} />}
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
          icon={<TriangleAlert size={18} />}
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

          @media (max-width: 1100px) {
            .dashboard-insights-grid {
              grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) !important;
            }
          }

          @media (max-width: 720px) {
            .dashboard-insights-grid {
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
                borderRadius: 6,
                display: 'grid',
                placeItems: 'center',
                background: tone.background
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

function TransactionsPanel({
  title,
  description,
  items,
  emptyText,
  viewAllLabel,
  onViewAll
}: {
  title: string
  description: string
  items: TransactionItem[]
  emptyText: string
  viewAllLabel: string
  onViewAll: () => void
}) {
  return (
    <section style={createDashboardPanelStyle()}>
      <div style={{ ...panelBodyStyle, display: 'grid', gap: 16 }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: 12
          }}
        >
          <SectionHeader icon={<ListChecks size={18} />} title={title} description={description} />
        </div>

        {items.length ? (
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
                    gap: 12,
                    ...createDashboardListItemStyle(tone.border, 'rgba(255, 255, 255, 0.68)', 12)
                  }}
                >
                  <span style={{ display: 'grid', gap: 4, minWidth: 0 }}>
                    <strong
                      style={{
                        fontSize: 13,
                        lineHeight: '17px',
                        fontWeight: 900,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap'
                      }}
                    >
                      {item.title}
                    </strong>
                    {item.subtitle ? (
                      <small
                        style={{
                          color: colors2000s.text.secondary,
                          fontSize: 11,
                          lineHeight: '14px',
                          fontWeight: 700,
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap'
                        }}
                      >
                        {item.subtitle}
                      </small>
                    ) : null}
                    <span
                      style={{
                        alignSelf: 'start',
                        padding: '3px 8px',
                        borderRadius: 999,
                        background: tone.background,
                        color: tone.accent,
                        fontSize: 9,
                        lineHeight: '11px',
                        fontWeight: 900,
                        letterSpacing: '0.06em',
                        textTransform: 'uppercase'
                      }}
                    >
                      {item.status}
                    </span>
                  </span>

                  <strong
                    style={{
                      color: colors2000s.text.primary,
                      fontSize: 13,
                      lineHeight: '17px',
                      fontWeight: 900,
                      whiteSpace: 'nowrap'
                    }}
                  >
                    {item.amount}
                  </strong>
                </div>
              )
            })}
          </div>
        ) : (
          <EmptyState text={emptyText} />
        )}

        <button
          type="button"
          onClick={onViewAll}
          style={{
            ...buttonStyles2000s.default,
            borderRadius: 6,
            padding: '10px 12px',
            justifySelf: 'start',
            fontSize: 11,
            lineHeight: '14px',
            fontWeight: 900,
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color: colors2000s.orange.accent
          }}
        >
          {viewAllLabel}
        </button>
      </div>
    </section>
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
            ...createDashboardListItemStyle(
              colors2000s.border.light,
              'rgba(255, 255, 255, 0.65)',
              14
            )
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0 }}>
            <span
              style={{
                width: 34,
                height: 34,
                borderRadius: 6,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
                background: 'rgba(255, 140, 66, 0.12)',
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
                  borderRadius: 6,
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

export default Dashboard
