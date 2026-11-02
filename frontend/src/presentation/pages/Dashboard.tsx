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
  DashboardQueryIssue,
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

  const featureFlagsAvailable = Boolean(featureFlagsQuery.data?.flags)
  const flags = featureFlagsQuery.data?.flags
  const paymentsEnabled = flags ? Boolean(flags.payments) : undefined
  const ledgerEnabled = flags ? Boolean(flags.ledger) : undefined

  const paymentsQuery = useReconciliationSummary(Boolean(paymentsEnabled && financialAdminAllowed))
  const outboxQuery = useOutboxStats(Boolean(paymentsEnabled && financialAdminAllowed))
  const ledgerQuery = useLedgerSummary(Boolean(ledgerEnabled && reportsAllowed))

  const summaryAvailable = Boolean(summaryQuery.data) && !summaryQuery.isError
  const stats = summaryAvailable ? summaryQuery.data?.stats : undefined
  const reportsAvailable = reportsAllowed && Boolean(reportsQuery.data) && !reportsQuery.isError
  const reportsUnavailableLabel = reportsAllowed ? 'No disponible' : 'Sin acceso'
  const reportsLoadingLabel =
    reportsAllowed && reportsQuery.isLoading ? 'Consultando...' : reportsUnavailableLabel
  const reportsPendingLabel =
    reportsAllowed && reportsQuery.isLoading ? 'Consultando...' : 'No disponible'
  const professionalsLoadingLabel =
    reportsAllowed && professionalsQuery.isLoading ? 'Consultando...' : reportsUnavailableLabel
  const reportStats = reportsAvailable ? reportsQuery.data?.stats : undefined
  const clientStats = reportsAvailable ? reportsQuery.data?.client_stats : undefined
  const professionalsAvailable =
    reportsAllowed && Boolean(professionalsQuery.data) && !professionalsQuery.isError
  const topProfessional = professionalsAvailable
    ? getTopProfessional(professionalsQuery.data?.professionals)
    : null
  const ledgerAvailable =
    reportsAllowed && Boolean(ledgerEnabled) && Boolean(ledgerQuery.data) && !ledgerQuery.isError
  const reportDebtAvailable = reportsAvailable && reportsQuery.data?.debt_summary !== undefined
  const debtAvailable = ledgerAvailable || reportDebtAvailable
  const outstandingBalance = ledgerAvailable
    ? Number(ledgerQuery.data?.total_balance)
    : reportDebtAvailable
      ? Number(reportsQuery.data?.debt_summary.outstanding_balance)
      : undefined
  const debtorsCount = ledgerAvailable
    ? Number(ledgerQuery.data?.debtors_count)
    : reportDebtAvailable
      ? Number(reportsQuery.data?.debt_summary.debtors_count)
      : undefined
  const upcomingAppointments = summaryAvailable
    ? (summaryQuery.data?.upcoming_appointments ?? [])
    : []
  const occupancy = summaryAvailable ? Number(stats?.occupancy_rate ?? 0) : undefined
  const availableCapacity = occupancy === undefined ? undefined : Math.max(0, 100 - occupancy)
  const paymentsQueriesEnabled = Boolean(paymentsEnabled && financialAdminAllowed)
  const reconciliationData = paymentsQuery.isError ? undefined : paymentsQuery.data
  const outboxStats = outboxQuery.isError ? undefined : outboxQuery.data
  const paymentsAvailable = paymentsQueriesEnabled && Boolean(reconciliationData)
  const outboxAvailable = paymentsQueriesEnabled && Boolean(outboxStats)
  const paymentErrors =
    paymentsAvailable && outboxAvailable
      ? Number(outboxStats?.pending_with_error ?? 0) +
        Number(reconciliationData?.failed_webhooks ?? 0)
      : undefined

  const queryIssues: DashboardQueryIssue[] = []
  const addQueryIssue = (
    id: string,
    title: string,
    message: string,
    refetch: () => Promise<unknown>,
    retrying: boolean
  ) => {
    queryIssues.push({ id, title, message, onRetry: () => void refetch(), retrying })
  }

  if (summaryQuery.isError) {
    addQueryIssue(
      'summary',
      'Resumen operativo',
      'No se pudieron cargar la agenda ni las métricas operativas.',
      summaryQuery.refetch,
      summaryQuery.isFetching
    )
  }

  if (featureFlagsQuery.isError) {
    addQueryIssue(
      'feature-flags',
      'Funciones de la tienda',
      'No pudimos confirmar qué módulos están activos.',
      featureFlagsQuery.refetch,
      featureFlagsQuery.isFetching
    )
  }
  if (reportsAllowed && reportsQuery.isError) {
    addQueryIssue(
      'reports',
      'Reportes del período',
      'No se pudieron cargar los indicadores ni las transacciones del período.',
      reportsQuery.refetch,
      reportsQuery.isFetching
    )
  }
  if (reportsAllowed && professionalsQuery.isError) {
    addQueryIssue(
      'professionals',
      'Rendimiento profesional',
      'No se pudo cargar el rendimiento de los profesionales.',
      professionalsQuery.refetch,
      professionalsQuery.isFetching
    )
  }
  if (reportsAllowed && trendQuery.isError) {
    addQueryIssue(
      'trend',
      'Tendencia',
      'No se pudo cargar la tendencia de los últimos meses.',
      trendQuery.refetch,
      trendQuery.isFetching
    )
  }
  if (featureFlagsAvailable && paymentsEnabled && financialAdminAllowed && paymentsQuery.isError) {
    addQueryIssue(
      'payments',
      'Resumen de cobros',
      'No se pudo consultar el estado de los cobros.',
      paymentsQuery.refetch,
      paymentsQuery.isFetching
    )
  }
  if (featureFlagsAvailable && paymentsEnabled && financialAdminAllowed && outboxQuery.isError) {
    addQueryIssue(
      'outbox',
      'Sincronización de cobros',
      'No se pudo consultar la sincronización de los cobros.',
      outboxQuery.refetch,
      outboxQuery.isFetching
    )
  }
  if (featureFlagsAvailable && ledgerEnabled && reportsAllowed && ledgerQuery.isError) {
    addQueryIssue(
      'ledger',
      'Cuentas pendientes',
      'No se pudo consultar el saldo de las cuentas pendientes.',
      ledgerQuery.refetch,
      ledgerQuery.isFetching
    )
  }

  const hasQueryErrors = queryIssues.length > 0
  const hasPartialAccess = !reportsAllowed || !financialAdminAllowed
  const isHealthLoading =
    summaryQuery.isLoading ||
    featureFlagsQuery.isLoading ||
    (reportsAllowed &&
      (reportsQuery.isLoading || professionalsQuery.isLoading || trendQuery.isLoading)) ||
    (paymentsEnabled &&
      financialAdminAllowed &&
      (paymentsQuery.isLoading || outboxQuery.isLoading)) ||
    (ledgerEnabled && reportsAllowed && ledgerQuery.isLoading)

  const requiresFollowup =
    (paymentErrors ?? 0) > 0 ||
    (summaryAvailable && Number(stats?.pending_confirmations ?? 0) > 0) ||
    (debtorsCount ?? 0) > 0
  const heroStatusLabel = hasQueryErrors
    ? 'datos incompletos'
    : isHealthLoading
      ? 'consultando...'
      : requiresFollowup
        ? 'requiere seguimiento'
        : hasPartialAccess
          ? 'vista parcial'
          : 'estable'

  const paymentsHealthValue =
    featureFlagsQuery.isError && !featureFlagsAvailable
      ? 'No disponible'
      : !featureFlagsAvailable
        ? 'Consultando...'
        : !paymentsEnabled
          ? 'deshabilitados'
          : !financialAdminAllowed
            ? 'Sin acceso'
            : paymentsQuery.isError || outboxQuery.isError
              ? 'No disponible'
              : !paymentsAvailable || !outboxAvailable
                ? 'Consultando...'
                : paymentErrors && paymentErrors > 0
                  ? `${numberFormatter.format(paymentErrors)} errores`
                  : 'sin fallas'

  const paymentsHealthTone =
    paymentsHealthValue === 'sin fallas'
      ? 'success'
      : paymentsHealthValue.endsWith('errores')
        ? 'danger'
        : 'neutral'

  const ledgerHealthValue =
    featureFlagsQuery.isError && !featureFlagsAvailable
      ? 'No disponible'
      : !featureFlagsAvailable
        ? 'Consultando...'
        : !ledgerEnabled
          ? 'desactivadas'
          : !reportsAllowed
            ? 'Sin acceso'
            : !debtAvailable
              ? ledgerQuery.isLoading || reportsQuery.isLoading
                ? 'Consultando...'
                : 'No disponible'
              : (debtorsCount ?? 0) > 0
                ? `${numberFormatter.format(debtorsCount ?? 0)} clientes con deuda`
                : 'sin deuda'

  const ledgerHealthTone = ledgerHealthValue.endsWith('clientes con deuda')
    ? 'warning'
    : ledgerHealthValue === 'sin deuda'
      ? 'success'
      : 'neutral'

  const hero: DashboardHero = {
    title: 'Hoy en Shifty',
    description: summaryAvailable
      ? `${numberFormatter.format(stats?.appointments_today ?? 0)} turnos, ${numberFormatter.format(
          stats?.pending_confirmations ?? 0
        )} pendientes, ocupación ${formatPercent(stats?.occupancy_rate)}.`
      : 'Agenda y ocupación no disponibles.',
    periodLabel: 'Corte operativo: hoy + últimos 7 días',
    statusLabel: heroStatusLabel,
    health: [
      {
        id: 'agenda',
        label: 'Agenda',
        value: !summaryAvailable
          ? 'No disponible'
          : Number(stats?.pending_confirmations ?? 0) > 0
            ? `${numberFormatter.format(stats?.pending_confirmations ?? 0)} pendientes`
            : 'al día',
        tone: !summaryAvailable
          ? 'neutral'
          : Number(stats?.pending_confirmations ?? 0) > 0
            ? 'warning'
            : 'success'
      },
      {
        id: 'pagos',
        label: 'Cobros online',
        value: paymentsHealthValue,
        tone: paymentsHealthTone
      },
      {
        id: 'ledger',
        label: 'Cuentas pendientes',
        value: ledgerHealthValue,
        tone: ledgerHealthTone
      },
      {
        id: 'ingresos',
        label: 'Ingresos',
        value: !summaryAvailable
          ? 'No disponible'
          : Number(stats?.revenue_trend ?? 0) < 0
            ? `${formatPercent(stats?.revenue_trend)} vs semana pasada`
            : `+${formatPercent(stats?.revenue_trend ?? 0)} de variación`,
        tone: !summaryAvailable
          ? 'neutral'
          : Number(stats?.revenue_trend ?? 0) < 0
            ? 'warning'
            : 'primary'
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
      value: summaryAvailable ? formatCurrency(stats?.weekly_revenue) : 'No disponible',
      detail: summaryAvailable
        ? `${Number(stats?.revenue_trend ?? 0) >= 0 ? '+' : ''}${formatPercent(
            stats?.revenue_trend
          )} vs semana pasada`
        : 'Dato no disponible',
      signal: summaryAvailable
        ? Number(stats?.revenue_trend ?? 0) >= 0
          ? 'Tendencia positiva'
          : 'Revisar caida'
        : 'No disponible',
      icon: <DollarSign size={18} />,
      tone: !summaryAvailable
        ? 'neutral'
        : Number(stats?.revenue_trend ?? 0) < 0
          ? 'warning'
          : 'success',
      onSelect: () => void navigate('/dashboard/reports')
    },
    {
      id: 'new-clients',
      label: 'Clientes nuevos',
      value: summaryAvailable
        ? numberFormatter.format(stats?.new_clients_last_30d ?? 0)
        : 'No disponible',
      detail: reportsAvailable
        ? `${numberFormatter.format(clientStats?.returning_clients ?? 0)} recurrentes activos`
        : reportsLoadingLabel,
      signal: !summaryAvailable
        ? 'No disponible'
        : Number(stats?.new_clients_last_30d ?? 0) > 0
          ? 'Adquisición en curso'
          : 'Sin altas recientes',
      icon: <UserRoundPlus size={18} />,
      tone: summaryAvailable ? 'success' : 'neutral',
      onSelect: () => void navigate('/dashboard/users')
    },
    {
      id: 'occupancy',
      label: 'Ocupación',
      value: summaryAvailable ? formatPercent(stats?.occupancy_rate) : 'No disponible',
      detail:
        availableCapacity === undefined
          ? 'Dato no disponible'
          : `${formatPercent(availableCapacity)} de capacidad libre`,
      signal:
        availableCapacity === undefined
          ? 'No disponible'
          : occupancy !== undefined && occupancy >= 85
            ? 'Día cargado'
            : availableCapacity >= 40
              ? 'Espacio para crecer'
              : 'Ritmo estable',
      icon: <Gauge size={18} />,
      tone: occupancy === undefined ? 'neutral' : occupancy >= 85 ? 'warning' : 'neutral',
      onSelect: () => void navigate('/dashboard/reports')
    },
    {
      id: 'cancellations',
      label: 'Cancelaciones',
      value: !reportsAvailable
        ? reportsPendingLabel
        : numberFormatter.format(reportStats?.cancelled_appointments ?? 0),
      detail: summaryAvailable
        ? `${numberFormatter.format(upcomingAppointments.length)} próximos en agenda`
        : 'Agenda no disponible',
      signal: !reportsAvailable
        ? reportsAllowed && reportsQuery.isLoading
          ? 'Consultando...'
          : 'Dato no disponible'
        : Number(reportStats?.cancelled_appointments ?? 0) > 0
          ? 'Revisar patron'
          : 'Sin cancelaciones',
      icon: <CalendarX size={18} />,
      tone: !reportsAvailable
        ? 'neutral'
        : Number(reportStats?.cancelled_appointments ?? 0) > 0
          ? 'warning'
          : 'success',
      onSelect: () => void navigate('/dashboard/reports')
    }
  ]

  const operationCards: DashboardOperationCard[] = [
    {
      title: 'Pendientes por confirmar',
      detail: !summaryAvailable
        ? 'Agenda no disponible'
        : Number(stats?.pending_confirmations ?? 0) > 0
          ? 'Hay reservas esperando decisión'
          : 'No hay confirmaciones pendientes',
      meta: summaryAvailable
        ? numberFormatter.format(stats?.pending_confirmations ?? 0)
        : 'No disponible',
      tone: !summaryAvailable
        ? 'neutral'
        : Number(stats?.pending_confirmations ?? 0) > 0
          ? 'warning'
          : 'success'
    },
    {
      title: 'Capacidad disponible',
      detail: summaryAvailable ? 'Espacio operativo libre para hoy' : 'Dato no disponible',
      meta: availableCapacity === undefined ? 'No disponible' : formatPercent(availableCapacity),
      tone:
        availableCapacity === undefined
          ? 'neutral'
          : availableCapacity < 15
            ? 'danger'
            : availableCapacity < 35
              ? 'warning'
              : 'success'
    },
    {
      title: 'Cancelaciones',
      detail: reportsAvailable
        ? 'Impacto registrado en el periodo'
        : reportsAllowed && reportsQuery.isLoading
          ? 'Consultando...'
          : 'Dato no disponible',
      meta: !reportsAvailable
        ? reportsPendingLabel
        : numberFormatter.format(reportStats?.cancelled_appointments ?? 0),
      tone: !reportsAvailable
        ? 'neutral'
        : Number(reportStats?.cancelled_appointments ?? 0) > 0
          ? 'warning'
          : 'neutral'
    },
    {
      title: 'Profesional destacado',
      detail: !professionalsAvailable
        ? professionalsLoadingLabel
        : topProfessional
          ? topProfessional.staff_name
          : 'Sin lider claro',
      meta: !professionalsAvailable
        ? professionalsLoadingLabel
        : topProfessional
          ? formatPercent(topProfessional.occupancy_rate)
          : '--',
      tone: professionalsAvailable && topProfessional ? 'primary' : 'neutral'
    }
  ]

  const urgentActions: ActionItem[] = []

  if (summaryAvailable && Number(stats?.pending_confirmations ?? 0) > 0) {
    urgentActions.push({
      id: 'confirmations',
      title: 'Confirmar turnos',
      description: 'Reservas esperando decisión',
      meta: numberFormatter.format(stats?.pending_confirmations ?? 0),
      tone: 'warning',
      onSelect: () => void navigate('/dashboard/calendar')
    })
  }

  if (paymentsAvailable && Number(reconciliationData?.pending_payments ?? 0) > 0) {
    urgentActions.push({
      id: 'pending-payments',
      title: 'Revisar cobros pendientes',
      description: formatCurrency(reconciliationData?.total_pending_amount),
      meta: numberFormatter.format(reconciliationData?.pending_payments ?? 0),
      tone: 'warning',
      onSelect: () => void navigate('/dashboard/collections')
    })
  }

  if (paymentErrors !== undefined && paymentErrors > 0) {
    urgentActions.push({
      id: 'payment-sync',
      title: 'Revisar cobros online',
      description: 'Hay pagos pendientes de actualizar',
      meta: numberFormatter.format(paymentErrors),
      tone: 'danger',
      onSelect: () => void navigate('/dashboard/payments')
    })
  }

  if (debtorsCount !== undefined && debtorsCount > 0) {
    urgentActions.push({
      id: 'debtors',
      title: 'Gestionar deuda',
      description:
        outstandingBalance === undefined
          ? 'Saldo no disponible'
          : formatCurrency(outstandingBalance),
      meta: numberFormatter.format(debtorsCount),
      tone: 'warning',
      onSelect: () => void navigate('/dashboard/ledger')
    })
  }

  const collectedAmount =
    paymentsAvailable && reconciliationData
      ? totalCollected(
          reconciliationData.total_approved_amount,
          reconciliationData.total_remainder_amount
        )
      : reportsAvailable
        ? reportStats?.total_revenue
        : undefined

  const moneyMetrics: MetricItem[] = [
    {
      id: 'approved-amount',
      label: 'Cobrado',
      value: collectedAmount === undefined ? 'No disponible' : formatCurrency(collectedAmount),
      detail: paymentsAvailable
        ? 'Pagos aprobados, manuales y restos'
        : reportsAvailable
          ? 'Ingresos por turnos'
          : 'Dato no disponible',
      tone: collectedAmount === undefined ? 'neutral' : 'success',
      onSelect: () =>
        void navigate(paymentsEnabled ? '/dashboard/collections' : '/dashboard/reports')
    },
    {
      id: 'average-ticket',
      label: 'Ticket promedio',
      value: reportsAvailable ? formatCurrency(reportStats?.average_ticket) : reportsLoadingLabel,
      detail: reportsAvailable ? 'Promedio móvil de 7 días' : reportsLoadingLabel,
      tone: 'neutral',
      onSelect: () => void navigate('/dashboard/reports')
    },
    {
      id: 'outstanding-balance',
      label: 'Saldo pendiente',
      value:
        outstandingBalance === undefined ? 'No disponible' : formatCurrency(outstandingBalance),
      detail:
        debtorsCount === undefined
          ? 'Saldo no disponible'
          : `${numberFormatter.format(debtorsCount)} clientes con deuda`,
      tone: (debtorsCount ?? 0) > 0 ? 'warning' : 'neutral',
      onSelect: () => void navigate('/dashboard/ledger')
    }
  ]

  const rankedItems: RankedItem[] = mapTopServices(
    reportsAvailable ? reportsQuery.data?.top_services : undefined
  )

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

  if (featureFlagsAvailable && !paymentsEnabled) {
    alerts.push({
      id: 'payments-disabled',
      title: 'Cobros online desactivados',
      description: 'No hay cobro automático activo',
      tone: 'neutral',
      onSelect: () => void navigate('/dashboard/settings')
    })
  }

  if (featureFlagsAvailable && !ledgerEnabled) {
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

  if (summaryAvailable && Number(stats?.revenue_trend ?? 0) < -15) {
    alerts.push({
      id: 'revenue-drop',
      title: 'Ingreso semanal en baja',
      description: `${formatPercent(stats?.revenue_trend)} contra la semana anterior`,
      tone: 'danger',
      onSelect: () => void navigate('/dashboard/reports')
    })
  }

  const opportunityCandidates: OpportunityItem[] = []

  if (availableCapacity !== undefined && availableCapacity >= 35) {
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
      reportsAllowed={reportsAllowed}
      copy={{
        ...copy,
        emptyAgenda: summaryAvailable
          ? copy.emptyAgenda
          : 'Agenda no disponible. Reintentá desde el aviso del panel.',
        emptyActions: financialAdminAllowed
          ? copy.emptyActions
          : 'Sin acceso a cobros y deuda para consultar otras tareas.',
        emptyTransactions: !reportsAllowed
          ? 'Sin acceso a reportes para consultar transacciones.'
          : reportsQuery.isLoading && !reportsAvailable
            ? 'Consultando transacciones...'
            : !reportsAvailable
              ? 'Transacciones no disponibles.'
              : copy.emptyTransactions,
        emptyAlerts: !reportsAllowed
          ? 'Sin acceso a reportes para consultar alertas.'
          : !reportsAvailable
            ? reportsQuery.isLoading
              ? 'Consultando alertas...'
              : 'Alertas no disponibles.'
            : copy.emptyAlerts,
        emptyOpportunities: !reportsAllowed
          ? 'Sin acceso a reportes para identificar oportunidades.'
          : !reportsAvailable || !professionalsAvailable
            ? reportsQuery.isLoading || professionalsQuery.isLoading
              ? 'Consultando oportunidades...'
              : 'Oportunidades no disponibles.'
            : copy.emptyOpportunities
      }}
      hero={hero}
      queryIssues={queryIssues}
      trendPoints={!reportsAllowed || trendQuery.isError ? [] : (trendQuery.data?.points ?? [])}
      trendLoading={trendQuery.isLoading}
      trendUnavailable={!reportsAllowed || Boolean(trendQuery.isError)}
      topServices={reportsAvailable ? (reportsQuery.data?.top_services ?? []) : []}
      salesLoading={reportsQuery.isLoading}
      salesUnavailable={!reportsAllowed || Boolean(reportsQuery.isError)}
      transactions={reportsAvailable ? mapTransactions(reportsQuery.data?.appointments) : []}
      transactionsUnavailable={!reportsAllowed || Boolean(reportsQuery.isError)}
      onViewTransactions={() => void navigate('/dashboard/reports')}
      todayMetrics={todayMetrics}
      urgentActions={urgentActions}
      agenda={mapAgenda(upcomingAppointments)}
      operationCards={operationCards}
      moneyMetrics={moneyMetrics}
      performanceItems={performanceItems}
      performanceLoading={
        reportsAllowed && (reportsQuery.isLoading || professionalsQuery.isLoading)
      }
      performanceUnavailable={
        performanceItems.length === 0 &&
        !reportsQuery.isLoading &&
        !professionalsQuery.isLoading &&
        (!reportsAvailable || !professionalsAvailable)
      }
      alerts={alerts}
      opportunities={opportunities}
      isLoading={summaryQuery.isLoading}
      errorMessage={summaryQuery.isError ? 'No se pudo cargar el resumen operativo.' : undefined}
    />
  )
}

export default Dashboard
