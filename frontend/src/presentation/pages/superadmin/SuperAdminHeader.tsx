import React from 'react'

import { Building2 } from 'lucide-react'

import type {
  SuperAdminCoupon,
  SuperAdminPlan,
  SuperAdminStoreOverview,
  SuperAdminStoreRow
} from '@application/services/SuperAdminService'

import { colors2000s } from '../../../theme/colors'
import { ActionButton } from '../SuperAdminUi'
import { emptyStateStyle, innerCardStyle, panelStyle, scopeBadgeStyle, statusLabel } from './shared'

/**
 * Seccion del panel SuperAdmin (descompuesto por dominio).
 * Presentacional puro: el estado y los handlers viven en SuperAdmin.tsx y
 * llegan por props con los mismos nombres que usaba el JSX original.
 */

interface SuperAdminHeaderProps {
  selectedStore: SuperAdminStoreRow | null
  hasSelectedStoreSubscription: boolean
  overview: SuperAdminStoreOverview | undefined
  activePlans: SuperAdminPlan[]
  activeCoupons: SuperAdminCoupon[]
  openCreateStoreModal: () => void
  openEditStoreModal: () => void
  openCreateAdminModal: () => void
  openAssignPlanModal: () => void
  openRedeemCouponModal: () => void
}

export const SuperAdminHeader: React.FC<SuperAdminHeaderProps> = ({
  selectedStore,
  hasSelectedStoreSubscription,
  overview,
  activePlans,
  activeCoupons,
  openCreateStoreModal,
  openEditStoreModal,
  openCreateAdminModal,
  openAssignPlanModal,
  openRedeemCouponModal
}) => (
  <section className="rounded-[2rem] p-6" style={panelStyle}>
    <div className="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <span
            className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
            style={scopeBadgeStyle('global')}
          >
            Alcance Global
          </span>
          <span
            className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
            style={scopeBadgeStyle('tenant')}
          >
            Tienda Seleccionada
          </span>
        </div>
        <div>
          <h1
            className="text-3xl font-black uppercase tracking-tight"
            style={{ color: colors2000s.text.primary }}
          >
            Control Global
          </h1>
          <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Operacion multi-tenant para tiendas, admins, suscripciones y cupones.
          </p>
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <ActionButton label="Crear tienda" onClick={openCreateStoreModal} tone="primary" />
        <ActionButton
          label="Editar tienda"
          onClick={openEditStoreModal}
          disabled={!selectedStore}
        />
        <ActionButton
          label="Crear admin"
          onClick={openCreateAdminModal}
          disabled={!selectedStore}
        />
        <ActionButton
          label="Asignar plan"
          onClick={openAssignPlanModal}
          disabled={!selectedStore || !activePlans.length}
        />
        <ActionButton
          label="Canjear cupon"
          onClick={openRedeemCouponModal}
          disabled={!selectedStore || !hasSelectedStoreSubscription || !activeCoupons.length}
        />
      </div>
    </div>

    <div className="mt-6 rounded-[1.75rem] p-5" style={innerCardStyle}>
      {selectedStore ? (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6">
            <div>
              <p
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Tienda activa
              </p>
              <p className="text-lg font-black" style={{ color: colors2000s.text.primary }}>
                {selectedStore.name}
              </p>
            </div>
            <div>
              <p
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Estado
              </p>
              <span
                className="inline-flex rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
                style={
                  selectedStore.is_active ? scopeBadgeStyle('tenant') : scopeBadgeStyle('danger')
                }
              >
                {statusLabel(selectedStore.is_active)}
              </span>
            </div>
            <div>
              <p
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Slug
              </p>
              <p className="font-black" style={{ color: colors2000s.text.primary }}>
                {selectedStore.slug}
              </p>
            </div>
            <div>
              <p
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Color de marca
              </p>
              <div className="mt-1 flex items-center gap-3">
                <span
                  className="h-5 w-5 rounded-full border"
                  style={{
                    background: selectedStore.primary_color,
                    borderColor: colors2000s.border.default
                  }}
                />
                <span className="font-black" style={{ color: colors2000s.text.primary }}>
                  {selectedStore.primary_color}
                </span>
              </div>
            </div>
            <div>
              <p
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                SLA booking
              </p>
              <p className="font-black" style={{ color: colors2000s.text.primary }}>
                {overview?.store.cancellation_hours ?? selectedStore.cancellation_hours}h cancel. /{' '}
                {overview?.store.buffer_minutes ?? selectedStore.buffer_minutes}m buffer
              </p>
            </div>
            <div>
              <p
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Suscripcion
              </p>
              <p className="font-black" style={{ color: colors2000s.text.primary }}>
                {selectedStore.current_plan_name || 'Sin suscripcion'}
              </p>
            </div>
          </div>

          <div
            className="rounded-2xl px-4 py-3"
            style={{ ...scopeBadgeStyle('danger'), boxShadow: colors2000s.shadows.outer }}
          >
            <p className="text-[10px] font-black uppercase tracking-widest">Protecciones</p>
            <p className="mt-1 text-[11px] font-bold">
              Revocar Super Admin, desactivar tienda, reemplazar suscripcion y canjear cupon tienen
              confirmacion y reglas de backend.
            </p>
          </div>
        </div>
      ) : (
        <div className="rounded-[1.5rem] p-8 text-center" style={emptyStateStyle}>
          <Building2 className="mx-auto mb-3 h-10 w-10 opacity-30" />
          <p
            className="text-sm font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.primary }}
          >
            No hay tienda seleccionada
          </p>
        </div>
      )}
    </div>
  </section>
)
