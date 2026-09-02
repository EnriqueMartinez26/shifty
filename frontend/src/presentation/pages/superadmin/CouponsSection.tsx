import React from 'react'

import { Tag } from 'lucide-react'

import type { SuperAdminCoupon } from '@application/services/SuperAdminService'

import { colors2000s } from '../../../theme/colors'
import { formatCurrencyEsAr, formatDateEsAr } from '../../lib/formatters'
import { ActionButton, MiniButton } from '../SuperAdminUi'
import {
  emptyStateStyle,
  innerCardStyle,
  isCouponExhausted,
  isCouponExpired,
  panelStyle,
  scopeBadgeStyle,
  type QueryState
} from './shared'

/**
 * Seccion del panel SuperAdmin (descompuesto por dominio).
 * Presentacional puro: el estado y los handlers viven en SuperAdmin.tsx y
 * llegan por props con los mismos nombres que usaba el JSX original.
 */

interface CouponsSectionProps {
  couponsQuery: QueryState<SuperAdminCoupon[]>
  openCreateCouponModal: () => void
  openEditCouponModal: (coupon: SuperAdminCoupon) => void
  toggleCouponActive: (coupon: SuperAdminCoupon) => Promise<void>
}

export const CouponsSection: React.FC<CouponsSectionProps> = ({
  couponsQuery,
  openCreateCouponModal,
  openEditCouponModal,
  toggleCouponActive
}) => (
  <section className="rounded-[2rem] p-6" style={panelStyle}>
    <div className="mb-4 flex items-center justify-between gap-3">
      <div>
        <span
          className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
          style={scopeBadgeStyle('global')}
        >
          Cupones
        </span>
        <h2
          className="mt-2 text-xl font-black uppercase tracking-tight"
          style={{ color: colors2000s.text.primary }}
        >
          Maestro editable
        </h2>
      </div>
      <ActionButton label="Crear cupon" onClick={openCreateCouponModal} tone="primary" />
    </div>

    <div className="space-y-3">
      {couponsQuery.data?.length ? (
        couponsQuery.data.map((coupon) => {
          const expired = isCouponExpired(coupon)
          const exhausted = isCouponExhausted(coupon)
          return (
            <div key={coupon.public_id} className="rounded-[1.5rem] p-4" style={innerCardStyle}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="font-black" style={{ color: colors2000s.text.primary }}>
                    {coupon.code}
                  </p>
                  <p
                    className="text-[10px] font-bold uppercase tracking-widest"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    {coupon.coupon_type} ·{' '}
                    {coupon.coupon_type === 'percent'
                      ? `${coupon.value}%`
                      : formatCurrencyEsAr(coupon.value, coupon.currency || 'ARS')}
                  </p>
                </div>
                <span
                  className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                  style={coupon.is_active ? scopeBadgeStyle('global') : scopeBadgeStyle('danger')}
                >
                  {coupon.current_uses}
                  {coupon.max_uses ? `/${coupon.max_uses}` : ''} usos
                </span>
              </div>

              <div
                className="mt-4 grid grid-cols-2 gap-3 text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                <div>
                  Vigencia:{' '}
                  <span style={{ color: colors2000s.text.primary }}>
                    {formatDateEsAr(coupon.valid_from)} a {formatDateEsAr(coupon.valid_until)}
                  </span>
                </div>
                <div>
                  Canje unico:{' '}
                  <span style={{ color: colors2000s.text.primary }}>
                    {coupon.one_time_per_store ? 'Si' : 'No'}
                  </span>
                </div>
              </div>

              {coupon.description ? (
                <p className="mt-3 text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
                  {coupon.description}
                </p>
              ) : null}

              {expired || exhausted ? (
                <div
                  className="mt-4 rounded-2xl px-3 py-2 text-[10px] font-black uppercase tracking-widest"
                  style={scopeBadgeStyle('danger')}
                >
                  {expired ? 'Cupon expirado' : 'Maximo de usos alcanzado'}
                </div>
              ) : null}

              <div className="mt-4 flex flex-wrap gap-2">
                <MiniButton
                  label="Editar"
                  onClick={(event) => {
                    event.stopPropagation()
                    openEditCouponModal(coupon)
                  }}
                  tone="primary"
                />
                <MiniButton
                  label={coupon.is_active ? 'Desactivar' : 'Activar'}
                  onClick={(event) => {
                    event.stopPropagation()
                    void toggleCouponActive(coupon)
                  }}
                  tone={coupon.is_active ? 'danger' : 'default'}
                />
              </div>
            </div>
          )
        })
      ) : (
        <div className="rounded-[1.5rem] p-8 text-center" style={emptyStateStyle}>
          <Tag className="mx-auto mb-3 h-10 w-10 opacity-25" />
          <p
            className="text-sm font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.primary }}
          >
            No hay cupones todavia
          </p>
          <p className="mt-2 text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Crea el primer cupon global para empezar a operar descuentos.
          </p>
        </div>
      )}
    </div>
  </section>
)
