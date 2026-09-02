import React from 'react'

import { CreditCard } from 'lucide-react'

import type {
  SuperAdminPlan,
  SuperAdminStoreOverview,
  SuperAdminStoreRow
} from '@application/services/SuperAdminService'

import { colors2000s } from '../../../theme/colors'
import { formatCurrencyEsAr, formatDateEsAr } from '../../lib/formatters'
import { ActionButton } from '../SuperAdminUi'
import { emptyStateStyle, innerCardStyle, panelStyle, scopeBadgeStyle } from './shared'

/**
 * Seccion del panel SuperAdmin (descompuesto por dominio).
 * Presentacional puro: el estado y los handlers viven en SuperAdmin.tsx y
 * llegan por props con los mismos nombres que usaba el JSX original.
 */

interface SubscriptionSectionProps {
  selectedStore: SuperAdminStoreRow | null
  overview: SuperAdminStoreOverview | undefined
  activePlans: SuperAdminPlan[]
  openAssignPlanModal: () => void
}

export const SubscriptionSection: React.FC<SubscriptionSectionProps> = ({
  selectedStore,
  overview,
  activePlans,
  openAssignPlanModal
}) => (
  <section className="rounded-[2rem] p-6" style={panelStyle}>
    <div className="mb-4 flex items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <CreditCard className="h-4 w-4" style={{ color: colors2000s.orange.accent }} />
        <span
          className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
          style={scopeBadgeStyle('tenant')}
        >
          Suscripcion
        </span>
      </div>
      <ActionButton
        label={overview?.subscription ? 'Reasignar plan' : 'Asignar plan'}
        onClick={openAssignPlanModal}
        disabled={!selectedStore || !activePlans.length}
      />
    </div>
    {overview?.subscription ? (
      <div className="rounded-[1.5rem] p-4" style={innerCardStyle}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="font-black" style={{ color: colors2000s.text.primary }}>
              {overview.subscription.plan_name || 'Plan sin nombre'}
            </p>
            <p
              className="text-[10px] font-bold uppercase tracking-widest"
              style={{ color: colors2000s.text.secondary }}
            >
              {overview.subscription.status} · {overview.subscription.billing_interval}
            </p>
          </div>
          <span
            className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
            style={scopeBadgeStyle('tenant')}
          >
            {formatCurrencyEsAr(overview.subscription.total_amount, overview.subscription.currency)}
          </span>
        </div>
        <div
          className="mt-4 grid grid-cols-2 gap-3 text-[10px] font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.secondary }}
        >
          <div>
            Base:{' '}
            <span style={{ color: colors2000s.text.primary }}>
              {formatCurrencyEsAr(
                overview.subscription.base_amount,
                overview.subscription.currency
              )}
            </span>
          </div>
          <div>
            Descuento:{' '}
            <span style={{ color: colors2000s.text.primary }}>
              {formatCurrencyEsAr(
                overview.subscription.discount_amount,
                overview.subscription.currency
              )}
            </span>
          </div>
          <div>
            Max staff:{' '}
            <span style={{ color: colors2000s.text.primary }}>
              {overview.subscription.max_staff ?? 'Libre'}
            </span>
          </div>
          <div>
            Max services:{' '}
            <span style={{ color: colors2000s.text.primary }}>
              {overview.subscription.max_services ?? 'Libre'}
            </span>
          </div>
          <div>
            Inicio:{' '}
            <span style={{ color: colors2000s.text.primary }}>
              {formatDateEsAr(overview.subscription.current_period_start)}
            </span>
          </div>
          <div>
            Fin:{' '}
            <span style={{ color: colors2000s.text.primary }}>
              {formatDateEsAr(overview.subscription.current_period_end)}
            </span>
          </div>
        </div>
        <div className="mt-4 rounded-2xl p-3" style={{ background: colors2000s.bg.button }}>
          <p
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            Cupon aplicado
          </p>
          <p className="mt-1 font-black" style={{ color: colors2000s.text.primary }}>
            {overview.subscription.applied_coupon?.code || 'Sin cupon aplicado'}
          </p>
        </div>
      </div>
    ) : (
      <div className="rounded-[1.5rem] p-8 text-center" style={emptyStateStyle}>
        <CreditCard className="mx-auto mb-3 h-10 w-10 opacity-25" />
        <p
          className="text-sm font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.primary }}
        >
          Esta tienda no tiene suscripcion
        </p>
        <p className="mt-2 text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
          Asigna un plan para habilitar billing y canjes sobre el tenant.
        </p>
      </div>
    )}
  </section>
)
