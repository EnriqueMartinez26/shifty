import type { ReactElement } from 'react'

import { AlertTriangle, BadgeCheck, CreditCard, Shield, Users } from 'lucide-react'

import type {
  SuperAdminStoreOverview,
  SuperAdminStoreRow
} from '@application/services/SuperAdminService'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'
import { subscriptionStatusLabel } from '../../lib/enumLabels'
import { formatDateEsAr } from '../../lib/formatters'
import { superAdminPalette } from '../../pages/superadmin/palette'

interface SuperAdminHealthPanelProps {
  selectedStore: SuperAdminStoreRow | null
  overview: SuperAdminStoreOverview | undefined
  overviewLoading: boolean
  overviewError: boolean
  overviewFetching: boolean
  onRetryOverview: () => void
  onCreateAdmin: () => void
  onAssignPlan: () => void
  onRedeemCoupon: () => void
  onEditStore: () => void
  activePlansCount: number | null
  activeCouponsCount: number | null
}

interface AlertItem {
  tone: 'danger' | 'warning' | 'good'
  title: string
  detail: string
}

const toneStyles = {
  danger: {
    background: colors2000s.status.danger.bg,
    border: `1px solid ${colors2000s.status.danger.border}`,
    color: colors2000s.status.danger.text
  },
  warning: {
    background: colors2000s.status.warning.bg,
    border: `1px solid ${colors2000s.status.warning.border}`,
    color: colors2000s.status.warning.text
  },
  good: {
    background: colors2000s.status.success.bg,
    border: `1px solid ${colors2000s.status.success.border}`,
    color: colors2000s.status.success.text
  }
} as const

function createAlerts(
  selectedStore: SuperAdminStoreRow | null,
  overview: SuperAdminStoreOverview | undefined
): AlertItem[] {
  if (!selectedStore) return []

  const alerts: AlertItem[] = []

  if (!selectedStore.is_active) {
    alerts.push({
      tone: 'danger',
      title: 'Tienda inactiva',
      detail: 'Puede bloquear alta de admins, suscripciones y operaciones sensibles.'
    })
  }

  if (!overview) return alerts

  const subscription = overview.subscription
  const activeAdmins = overview.users.admins.filter((admin) => admin.is_active).length
  const activeUsers = overview.users.active_users_count

  if (!subscription) {
    alerts.push({
      tone: 'warning',
      title: 'Sin suscripción',
      detail: 'La tienda no tiene un plan asignado.'
    })
  } else if (subscription.status !== 'active') {
    alerts.push({
      tone: 'warning',
      title: `Suscripción ${subscriptionStatusLabel(subscription.status).toLowerCase()}`,
      detail: 'Conviene revisar el cobro y el período vigente antes de seguir operando.'
    })
  } else {
    alerts.push({
      tone: 'good',
      title: 'Suscripción al día',
      detail: `Renueva ${formatDateEsAr(subscription.current_period_end)}.`
    })
  }

  if (activeAdmins === 0) {
    alerts.push({
      tone: 'danger',
      title: 'Sin admins activos',
      detail: 'La tienda no tiene un responsable activo para operar el panel.'
    })
  }

  if (activeUsers === 0) {
    alerts.push({
      tone: 'warning',
      title: 'Sin usuarios activos',
      detail: 'Puede ser una tienda recién creada o desatendida.'
    })
  }

  if (!alerts.length) {
    alerts.push({
      tone: 'good',
      title: 'Estado saludable',
      detail: 'No hay señales críticas inmediatas en tienda, usuarios o suscripción.'
    })
  }

  return alerts
}

export function SuperAdminHealthPanel({
  selectedStore,
  overview,
  overviewLoading,
  overviewError,
  overviewFetching,
  onRetryOverview,
  onCreateAdmin,
  onAssignPlan,
  onRedeemCoupon,
  onEditStore,
  activePlansCount,
  activeCouponsCount
}: SuperAdminHealthPanelProps): ReactElement {
  const alerts = createAlerts(selectedStore, overview)
  const stats = [
    {
      label: 'Admins activos',
      value: overview ? overview.users.admins.filter((admin) => admin.is_active).length : null,
      icon: Shield
    },
    {
      label: 'Usuarios activos',
      value: overview?.users.active_users_count ?? null,
      icon: Users
    },
    {
      label: 'Canjes recientes',
      value: overview?.recent_redemptions.length ?? null,
      icon: BadgeCheck
    },
    {
      label: 'Planes disponibles',
      value: activePlansCount,
      icon: CreditCard
    }
  ]

  return (
    <section
      className="rounded-[2rem] p-6"
      style={{
        background: 'white',
        border: `1px solid ${colors2000s.border.default}`,
        boxShadow: colors2000s.shadows.outer
      }}
    >
      <div className="mb-4 flex items-center gap-2">
        <AlertTriangle className="h-4 w-4" style={{ color: superAdminPalette.icon }} />
        <div>
          <p
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            Salud operativa
          </p>
          <h2
            className="mt-1 text-xl font-black uppercase tracking-tight"
            style={{ color: colors2000s.text.primary }}
          >
            Resumen
          </h2>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        {stats.map(({ label, value, icon: Icon }) => (
          <div
            key={label}
            className="rounded-[1.5rem] p-4"
            style={{
              background: colors2000s.bg.button,
              border: `1px solid ${colors2000s.border.light}`
            }}
          >
            <div className="flex items-center gap-2">
              <Icon className="h-4 w-4" style={{ color: superAdminPalette.icon }} />
              <span
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                {label}
              </span>
            </div>
            <p
              className="mt-3 text-2xl font-black"
              style={{ color: colors2000s.text.primary }}
              aria-label={value === null ? `${label}: sin datos` : undefined}
            >
              {value ?? '—'}
            </p>
          </div>
        ))}
      </div>

      {overviewLoading && !overview ? (
        <p
          role="status"
          className="mt-4 rounded-[1.5rem] px-4 py-3 text-xs font-bold"
          style={{ background: colors2000s.bg.button, color: colors2000s.text.secondary }}
        >
          Cargando estado operativo...
        </p>
      ) : null}

      {overviewError ? (
        <div
          role="alert"
          aria-live="assertive"
          aria-atomic="true"
          className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-[1.5rem] px-4 py-3"
          style={{
            background: colors2000s.status.danger.bg,
            border: `1px solid ${colors2000s.status.danger.border}`,
            color: colors2000s.status.danger.text
          }}
        >
          <p className="text-xs font-bold">
            {overview
              ? 'No se pudo actualizar este resumen. Se muestran los últimos datos disponibles.'
              : 'No se pudo cargar el estado operativo de esta tienda.'}
          </p>
          <button
            type="button"
            onClick={onRetryOverview}
            disabled={overviewFetching}
            className="min-h-11 rounded-xl px-4 py-3 text-[10px] font-black uppercase tracking-widest focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-60"
            style={buttonStyles2000s.default}
          >
            {overviewFetching ? 'Reintentando...' : 'Reintentar resumen'}
          </button>
        </div>
      ) : null}

      {!selectedStore ? (
        <p
          role="status"
          className="mt-4 rounded-[1.5rem] px-4 py-3 text-xs font-bold"
          style={{ background: colors2000s.bg.button, color: colors2000s.text.secondary }}
        >
          Seleccioná una tienda para consultar su estado operativo.
        </p>
      ) : null}

      {selectedStore && !overview && !overviewLoading && !overviewError ? (
        <p
          role="status"
          className="mt-4 rounded-[1.5rem] px-4 py-3 text-xs font-bold"
          style={{ background: colors2000s.bg.button, color: colors2000s.text.secondary }}
        >
          El estado operativo todavía no está disponible.
        </p>
      ) : null}

      <div className="mt-4 space-y-3">
        {alerts.map((alert) => (
          <div
            key={`${alert.title}-${alert.detail}`}
            className="rounded-[1.5rem] px-4 py-3"
            style={toneStyles[alert.tone]}
          >
            <p className="text-[10px] font-black uppercase tracking-widest">{alert.title}</p>
            <p className="mt-1 text-xs font-bold">{alert.detail}</p>
          </div>
        ))}
      </div>

      <div className="mt-5 rounded-[1.5rem] p-4" style={{ background: colors2000s.bg.button }}>
        <p
          className="text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          Quick support actions
        </p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          <button
            type="button"
            onClick={onEditStore}
            className="rounded-2xl px-4 py-3 text-[10px] font-black uppercase tracking-widest"
            style={{ background: '#fff', border: `1px solid ${colors2000s.border.default}` }}
          >
            Ajustar tienda
          </button>
          <button
            type="button"
            onClick={onCreateAdmin}
            // La tienda interna solo aloja cuentas SuperAdmin (2026-10-10).
            disabled={!selectedStore || selectedStore.is_internal}
            className="rounded-2xl px-4 py-3 text-[10px] font-black uppercase tracking-widest disabled:opacity-50"
            style={{ background: '#fff', border: `1px solid ${colors2000s.border.default}` }}
          >
            Crear admin
          </button>
          <button
            type="button"
            onClick={onAssignPlan}
            disabled={!selectedStore || activePlansCount === null || activePlansCount === 0}
            className="rounded-2xl px-4 py-3 text-[10px] font-black uppercase tracking-widest disabled:opacity-50"
            style={{ background: '#fff', border: `1px solid ${colors2000s.border.default}` }}
          >
            Asignar plan
          </button>
          <button
            type="button"
            onClick={onRedeemCoupon}
            disabled={
              !selectedStore ||
              !overview?.subscription ||
              activeCouponsCount === null ||
              activeCouponsCount === 0
            }
            className="rounded-2xl px-4 py-3 text-[10px] font-black uppercase tracking-widest disabled:opacity-50"
            style={{ background: '#fff', border: `1px solid ${colors2000s.border.default}` }}
          >
            Aplicar cupón
          </button>
        </div>
      </div>
    </section>
  )
}
