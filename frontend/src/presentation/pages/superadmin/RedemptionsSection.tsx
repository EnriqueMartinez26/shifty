import React from 'react'

import { Tag } from 'lucide-react'

import type {
  SuperAdminCoupon,
  SuperAdminStoreOverview,
  SuperAdminStoreRow
} from '@application/services/SuperAdminService'

import { colors2000s } from '../../../theme/colors'
import { formatCurrencyEsAr, formatDateTimeEsAr } from '../../lib/formatters'
import { ActionButton } from '../SuperAdminUi'
import { emptyStateStyle, innerCardStyle, panelStyle, scopeBadgeStyle } from './shared'

/**
 * Seccion del panel SuperAdmin (descompuesto por dominio).
 * Presentacional puro: el estado y los handlers viven en SuperAdmin.tsx y
 * llegan por props con los mismos nombres que usaba el JSX original.
 */

interface RedemptionsSectionProps {
  selectedStore: SuperAdminStoreRow | null
  hasSelectedStoreSubscription: boolean
  overview: SuperAdminStoreOverview | undefined
  activeCoupons: SuperAdminCoupon[]
  openRedeemCouponModal: () => void
}

export const RedemptionsSection: React.FC<RedemptionsSectionProps> = ({
  selectedStore,
  hasSelectedStoreSubscription,
  overview,
  activeCoupons,
  openRedeemCouponModal
}) => (
  <section className="rounded-[2rem] p-6" style={panelStyle}>
    <div className="mb-4 flex items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <Tag className="h-4 w-4" style={{ color: colors2000s.orange.accent }} />
        <span
          className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
          style={scopeBadgeStyle('tenant')}
        >
          Canjes
        </span>
      </div>
      <ActionButton
        label="Canjear cupon"
        onClick={openRedeemCouponModal}
        disabled={!selectedStore || !hasSelectedStoreSubscription || !activeCoupons.length}
      />
    </div>
    {overview?.recent_redemptions.length ? (
      <div className="space-y-3">
        {overview.recent_redemptions.map((redemption) => (
          <div key={redemption.public_id} className="rounded-[1.5rem] p-4" style={innerCardStyle}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-black" style={{ color: colors2000s.text.primary }}>
                  {redemption.code_snapshot}
                </p>
                <p
                  className="text-[10px] font-bold uppercase tracking-widest"
                  style={{ color: colors2000s.text.secondary }}
                >
                  {redemption.coupon_type_snapshot} · {formatDateTimeEsAr(redemption.created_at)}
                </p>
              </div>
              <span
                className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                style={scopeBadgeStyle('tenant')}
              >
                -{formatCurrencyEsAr(redemption.discount_amount, redemption.currency)}
              </span>
            </div>
            <p
              className="mt-3 text-[10px] font-black uppercase tracking-widest"
              style={{ color: colors2000s.text.secondary }}
            >
              Final:{' '}
              <span style={{ color: colors2000s.text.primary }}>
                {formatCurrencyEsAr(redemption.final_amount, redemption.currency)}
              </span>
            </p>
          </div>
        ))}
      </div>
    ) : (
      <div className="rounded-[1.5rem] p-8 text-center" style={emptyStateStyle}>
        <Tag className="mx-auto mb-3 h-10 w-10 opacity-25" />
        <p
          className="text-sm font-black uppercase tracking-widest"
          style={{ color: colors2000s.text.primary }}
        >
          No hay canjes recientes
        </p>
      </div>
    )}
  </section>
)
