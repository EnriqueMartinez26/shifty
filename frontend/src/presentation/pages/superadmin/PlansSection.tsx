import React from 'react'

import type { SuperAdminPlan } from '@application/services/SuperAdminService'

import { colors2000s } from '../../../theme/colors'
import { formatCurrencyEsAr } from '../../lib/formatters'
import { ActionButton, MiniButton } from '../SuperAdminUi'
import { innerCardStyle, panelStyle, scopeBadgeStyle, type QueryState } from './shared'

/**
 * Seccion del panel SuperAdmin (descompuesto por dominio).
 * Presentacional puro: el estado y los handlers viven en SuperAdmin.tsx y
 * llegan por props con los mismos nombres que usaba el JSX original.
 */

interface PlansSectionProps {
  plansQuery: QueryState<SuperAdminPlan[]>
  openCreatePlanModal: () => void
  openEditPlanModal: (plan: SuperAdminPlan) => void
  togglePlanActive: (plan: SuperAdminPlan) => Promise<void>
}

export const PlansSection: React.FC<PlansSectionProps> = ({
  plansQuery,
  openCreatePlanModal,
  openEditPlanModal,
  togglePlanActive
}) => (
  <section className="rounded-[2rem] p-6" style={panelStyle}>
    <div className="mb-4 flex items-center justify-between gap-3">
      <div>
        <span
          className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
          style={scopeBadgeStyle('global')}
        >
          Planes
        </span>
        <h2
          className="mt-2 text-xl font-black uppercase tracking-tight"
          style={{ color: colors2000s.text.primary }}
        >
          Catalogo global
        </h2>
      </div>
      <ActionButton label="Crear plan" onClick={openCreatePlanModal} tone="primary" />
    </div>

    <div className="space-y-3">
      {plansQuery.data?.map((plan) => (
        <div key={plan.public_id} className="rounded-[1.5rem] p-4" style={innerCardStyle}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="font-black" style={{ color: colors2000s.text.primary }}>
                {plan.name}
              </p>
              <p
                className="text-[10px] font-bold uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                {plan.billing_interval} · {formatCurrencyEsAr(plan.price, plan.currency)}
              </p>
            </div>
            <span
              className="rounded-full px-3 py-1 text-[10px] font-black uppercase tracking-widest"
              style={plan.is_active ? scopeBadgeStyle('global') : scopeBadgeStyle('danger')}
            >
              {plan.is_active ? 'Activo' : 'Inactivo'}
            </span>
          </div>

          <div
            className="mt-4 grid grid-cols-3 gap-3 text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            <div>
              Max staff:{' '}
              <span style={{ color: colors2000s.text.primary }}>{plan.max_staff ?? 'Libre'}</span>
            </div>
            <div>
              Max services:{' '}
              <span style={{ color: colors2000s.text.primary }}>
                {plan.max_services ?? 'Libre'}
              </span>
            </div>
            <div>
              Ciclo:{' '}
              <span style={{ color: colors2000s.text.primary }}>{plan.billing_interval}</span>
            </div>
          </div>

          {plan.description ? (
            <p className="mt-4 text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
              {plan.description}
            </p>
          ) : null}

          <div className="mt-4 flex flex-wrap gap-2">
            <MiniButton
              label="Editar"
              onClick={(event) => {
                event.stopPropagation()
                openEditPlanModal(plan)
              }}
              tone="primary"
            />
            <MiniButton
              label={plan.is_active ? 'Desactivar' : 'Activar'}
              onClick={(event) => {
                event.stopPropagation()
                void togglePlanActive(plan)
              }}
              tone={plan.is_active ? 'danger' : 'default'}
            />
          </div>
        </div>
      ))}
    </div>
  </section>
)
