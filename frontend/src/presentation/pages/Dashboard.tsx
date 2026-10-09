import { useMemo } from 'react'

import { subDays } from 'date-fns'
import { CalendarX, DollarSign, Gauge, UserRoundPlus } from 'lucide-react'
import { useNavigate } from 'react-router'

import { totalCollected } from '@domain/value-objects/AppointmentCharge'

import { formatArgentinaDate } from '@shared/utils/argentinaTime'
import { formatCurrency } from '@shared/utils/currency'

import { copy } from '../components/organisms/dashboard/dashboardCopy'
import {
  formatPercent,
  numberFormatter
} from '../components/organisms/dashboard/dashboardFormatters'
import {
  getTopProfessional,
  mapAgenda,
  mapTopServices,
  mapTransactions
} from '../components/organisms/dashboard/dashboardMappers'
import EnterpriseDashboard from '../components/organisms/dashboard/EnterpriseDashboard'
import type {
  ActionItem,
  DashboardHero,
  DashboardOperationCard,
  MetricItem,
  OpportunityItem,
  RankedItem
} from '../components/organisms/dashboard/types'
import { useAuth } from '../context/AuthContext'
import { ROLE_PROFESSIONAL, ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN } from '../context/roles'
import { useDashboardSummary } from '../hooks/useDashboard'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import { useLedgerSummary } from '../hooks/useLedger'
import { useOutboxStats, useReconciliationSummary } from '../hooks/usePayments'
import { useProfessionalReports, useReportSummary, useReportTrend } from '../hooks/useReports'
import { useStoreFeatureFlags } from '../hooks/useStores'

const canViewReports = (role: string | undefined, isGlobalAdmin: boolean) =>
  isGlobalAdmin ||
  role === ROLE_STORE_ADMIN ||
  role === ROLE_SUPER_ADMIN ||
  role === ROLE_PROFESSIONAL

const canViewFinancialAdmin = (role: string | undefined, isGlobalAdmin: boolean) =>
  isGlobalAdmin || role === ROLE_STORE_ADMIN || role === ROLE_SUPER_ADMIN

const Dashboard = () => {
  useDocumentTitle('Dashboard · Shifty')
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
    )} pendientes, ocupación ${formatPercent(stats?.occupancy_rate)}.`,
    periodLabel: 'Corte operativo: hoy + últimos 7 días',
    statusLabel: heroStatusLabel,
    health: [
      {
        id: 'agenda',
        label: 'Agenda',
        value:
          Number(stats?.pending_confirmations ?? 0) > 0
            ? `${numberFormatter.format(stats?.pending_confirmations ?? 0)} pendientes`
            : 'al día',
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
            : `+${formatPercent(stats?.revenue_trend ?? 0)} de variación`,
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
        description: 'Ir a cobros pendientes del día',
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
          ? 'Adquisición en curso'
          : 'Sin altas recientes',
      icon: <UserRoundPlus size={18} />,
      tone: 'success',
      onSelect: () => void navigate('/dashboard/users')
    },
    {
      id: 'occupancy',
      label: 'Ocupación',
      value: formatPercent(stats?.occupancy_rate),
      detail: `${formatPercent(availableCapacity)} de capacidad libre`,
      signal:
        occupancy >= 85
          ? 'Día cargado'
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
      detail: `${numberFormatter.format(upcomingAppointments.length)} próximos en agenda`,
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
          ? 'Hay reservas esperando decisión'
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
      description: 'Reservas esperando decisión',
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
        paymentsQuery.data
          ? totalCollected(
              paymentsQuery.data.total_approved_amount,
              paymentsQuery.data.total_remainder_amount
            )
          : reportStats?.total_revenue
      ),
      detail: paymentsEnabled ? 'Pagos aprobados, manuales y restos' : 'Ingresos por turnos',
      tone: 'success',
      onSelect: () =>
        void navigate(paymentsEnabled ? '/dashboard/collections' : '/dashboard/reports')
    },
    {
      id: 'average-ticket',
      label: 'Ticket promedio',
      value: formatCurrency(reportStats?.average_ticket),
      detail: 'Promedio móvil de 7 días',
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
      description: 'No hay cobro automático activo',
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
      title: 'Día con capacidad libre',
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

export default Dashboard
