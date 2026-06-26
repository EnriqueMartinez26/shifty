import type { ReactElement } from 'react'

import { AlertTriangle, BadgeCheck, CreditCard, Shield, Users } from 'lucide-react'

import type {
  SuperAdminStoreOverview,
  SuperAdminStoreRow
} from '@application/services/SuperAdminService'

import { colors2000s } from '../../../theme/colors'
import { formatDateEsAr } from '../../lib/formatters'

interface SuperAdminHealthPanelProps {
  selectedStore: SuperAdminStoreRow | null
  overview: SuperAdminStoreOverview | undefined
  onCreateAdmin: () => void
  onAssignPlan: () => void
  onRedeemCoupon: () => void
  onEditStore: () => void
  activePlansCount: number
  activeCouponsCount: number
}

interface AlertItem {
  tone: 'danger' | 'warning' | 'good'
  title: string
  detail: string
}

const toneStyles = {
  danger: {
    background: '#fff1f2',
    border: '1px solid #fecdd3',
    color: '#be123c'
  },
  warning: {
    background: '#fff7ed',
    border: `1px solid ${colors2000s.orange.light}`,
    color: colors2000s.orange.accent
  },
  good: {
    background: '#ecfdf5',
    border: '1px solid #bbf7d0',
    color: '#15803d'
  }
} as const

function createAlerts(
  selectedStore: SuperAdminStoreRow | null,
  overview: SuperAdminStoreOverview | undefined
): AlertItem[] {
  if (!selectedStore) return []

  const alerts: AlertItem[] = []
  const subscription = overview?.subscription
  const activeAdmins = overview?.users.admins.filter((admin) => admin.is_active).length ?? 0
  const activeUsers = overview?.users.active_users_count ?? 0

  if (!selectedStore.is_active) {
    alerts.push({
      tone: 'danger',
      title: 'Tenant inactivo',
      detail: 'Puede bloquear alta de admins, suscripciones y operaciones sensibles.'
    })
  }

  if (!subscription) {
    alerts.push({
      tone: 'warning',
      title: 'Sin suscripción',
      detail: 'El tenant quedó fuera del flujo comercial principal.'
    })
  } else if (subscription.status !== 'active') {
    alerts.push({
      tone: 'warning',
      title: `Suscripción ${subscription.status}`,
      detail: 'Conviene revisar billing y período vigente antes de seguir operando.'
    })
  } else {
    alerts.push({
      tone: 'good',
      title: 'Billing operativo',
      detail: `Renueva ${formatDateEsAr(subscription.current_period_end)}.`
    })
  }

  if (activeAdmins === 0) {
    alerts.push({
      tone: 'danger',
      title: 'Sin admins activos',
      detail: 'El tenant no tiene un responsable activo para operar el backoffice.'
    })
  }

  if (activeUsers === 0) {
    alerts.push({
      tone: 'warning',
      title: 'Sin usuarios activos',
      detail: 'Puede ser un tenant recién creado o directamente desatendido.'
    })
  }

  if (!alerts.length) {
    alerts.push({
      tone: 'good',
      title: 'Estado saludable',
      detail: 'No hay señales críticas inmediatas en tienda, usuarios o billing.'
    })
  }

  return alerts
}

export function SuperAdminHealthPanel({
  selectedStore,
  overview,
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
      value: overview?.users.admins.filter((admin) => admin.is_active).length ?? 0,
      icon: Shield
    },
    {
      label: 'Usuarios activos',
      value: overview?.users.active_users_count ?? 0,
      icon: Users
    },
    {
      label: 'Canjes recientes',
      value: overview?.recent_redemptions.length ?? 0,
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
        <AlertTriangle className="h-4 w-4" style={{ color: colors2000s.orange.accent }} />
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
            Executive summary
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
              <Icon className="h-4 w-4" style={{ color: colors2000s.orange.accent }} />
              <span
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                {label}
              </span>
            </div>
            <p className="mt-3 text-2xl font-black" style={{ color: colors2000s.text.primary }}>
              {value}
            </p>
          </div>
        ))}
      </div>

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
            Ajustar tenant
          </button>
          <button
            type="button"
            onClick={onCreateAdmin}
            disabled={!selectedStore}
            className="rounded-2xl px-4 py-3 text-[10px] font-black uppercase tracking-widest disabled:opacity-50"
            style={{ background: '#fff', border: `1px solid ${colors2000s.border.default}` }}
          >
            Crear admin
          </button>
          <button
            type="button"
            onClick={onAssignPlan}
            disabled={!selectedStore || !activePlansCount}
            className="rounded-2xl px-4 py-3 text-[10px] font-black uppercase tracking-widest disabled:opacity-50"
            style={{ background: '#fff', border: `1px solid ${colors2000s.border.default}` }}
          >
            Asignar plan
          </button>
          <button
            type="button"
            onClick={onRedeemCoupon}
            disabled={!selectedStore || !overview?.subscription || !activeCouponsCount}
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
