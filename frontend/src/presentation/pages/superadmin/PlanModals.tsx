import React from 'react'

import type { SuperAdminPlan, SuperAdminStoreRow } from '@application/services/SuperAdminService'

import { SuperAdminFormModal } from '../../components/organisms/SuperAdminFormModal'
import { formatCurrencyEsAr } from '../../lib/formatters'
import { FieldLabel, SelectInput, TextArea, TextInput, ToggleRow } from '../SuperAdminUi'
import {
  formGridClass,
  scopeBadgeStyle,
  type PendingState,
  type PlanFormState,
  type SubscriptionFormState,
  type SuperAdminModalKey
} from './shared'

/**
 * Modales del panel SuperAdmin, agrupados por dominio.
 *
 * El estado y los handlers siguen viviendo en SuperAdmin.tsx (el contenedor);
 * estos componentes son presentacionales: reciben todo por props con los
 * mismos nombres para que el JSX movido quede identico al original.
 */

interface PlanModalsProps {
  modal: SuperAdminModalKey
  closeModal: () => void
  modalError: string | null
  selectedStore: SuperAdminStoreRow | null
  selectedStoreUnavailable: boolean
  activePlans: SuperAdminPlan[]
  planForm: PlanFormState
  setPlanForm: React.Dispatch<React.SetStateAction<PlanFormState>>
  handlePlanSubmit: (event: React.FormEvent<HTMLFormElement>) => Promise<void>
  createPlanMutation: PendingState
  updatePlanMutation: PendingState
  subscriptionForm: SubscriptionFormState
  setSubscriptionForm: React.Dispatch<React.SetStateAction<SubscriptionFormState>>
  handleSubscriptionSubmit: (event: React.FormEvent<HTMLFormElement>) => Promise<void>
  assignSubscriptionMutation: PendingState
}

export const PlanModals: React.FC<PlanModalsProps> = ({
  modal,
  closeModal,
  modalError,
  selectedStore,
  selectedStoreUnavailable,
  activePlans,
  planForm,
  setPlanForm,
  handlePlanSubmit,
  createPlanMutation,
  updatePlanMutation,
  subscriptionForm,
  setSubscriptionForm,
  handleSubscriptionSubmit,
  assignSubscriptionMutation
}) => (
  <>
    <SuperAdminFormModal
      isOpen={modal === 'create-plan' || modal === 'edit-plan'}
      onClose={closeModal}
      onSubmit={handlePlanSubmit}
      title={modal === 'create-plan' ? 'Crear plan' : 'Editar plan'}
      subtitle="Gestiona nombre, precio, limites operativos y estado comercial."
      submitLabel={modal === 'create-plan' ? 'Crear plan' : 'Guardar plan'}
      loading={createPlanMutation.isPending || updatePlanMutation.isPending}
      error={modalError}
    >
      <div className={formGridClass}>
        <div>
          <FieldLabel>Nombre</FieldLabel>
          <TextInput
            value={planForm.name}
            onChange={(event) =>
              setPlanForm((current) => ({ ...current, name: event.target.value }))
            }
            required
          />
        </div>
        <div>
          <FieldLabel>Intervalo</FieldLabel>
          <SelectInput
            value={planForm.billing_interval}
            onChange={(event) =>
              setPlanForm((current) => ({ ...current, billing_interval: event.target.value }))
            }
          >
            <option value="monthly">Mensual</option>
            <option value="quarterly">Trimestral</option>
            <option value="yearly">Anual</option>
            <option value="custom">Personalizado</option>
          </SelectInput>
        </div>
      </div>

      <div>
        <FieldLabel>Descripcion</FieldLabel>
        <TextArea
          value={planForm.description}
          onChange={(event) =>
            setPlanForm((current) => ({ ...current, description: event.target.value }))
          }
        />
      </div>

      <div className={formGridClass}>
        <div>
          <FieldLabel>Precio</FieldLabel>
          <TextInput
            type="number"
            min="0"
            step="0.01"
            value={planForm.price}
            onChange={(event) =>
              setPlanForm((current) => ({ ...current, price: event.target.value }))
            }
            required
          />
        </div>
        <div>
          <FieldLabel>Moneda</FieldLabel>
          <TextInput
            value={planForm.currency}
            onChange={(event) =>
              setPlanForm((current) => ({
                ...current,
                currency: event.target.value.toUpperCase()
              }))
            }
            required
          />
        </div>
      </div>

      <div className={formGridClass}>
        <div>
          <FieldLabel>Max staff</FieldLabel>
          <TextInput
            type="number"
            min="0"
            value={planForm.max_staff}
            onChange={(event) =>
              setPlanForm((current) => ({ ...current, max_staff: event.target.value }))
            }
            placeholder="Libre"
          />
        </div>
        <div>
          <FieldLabel>Max services</FieldLabel>
          <TextInput
            type="number"
            min="0"
            value={planForm.max_services}
            onChange={(event) =>
              setPlanForm((current) => ({ ...current, max_services: event.target.value }))
            }
            placeholder="Libre"
          />
        </div>
      </div>

      {modal === 'edit-plan' ? (
        <ToggleRow
          label="Plan activo"
          description="Define si puede asignarse a nuevas tiendas."
          checked={planForm.is_active}
          onToggle={() => setPlanForm((current) => ({ ...current, is_active: !current.is_active }))}
        />
      ) : null}
    </SuperAdminFormModal>

    <SuperAdminFormModal
      isOpen={modal === 'assign-plan'}
      onClose={closeModal}
      onSubmit={handleSubscriptionSubmit}
      title="Asignar plan"
      subtitle={selectedStore ? `Suscripcion de ${selectedStore.name}` : 'Suscripcion por tienda'}
      submitLabel="Guardar suscripcion"
      loading={assignSubscriptionMutation.isPending}
      error={modalError}
      submitDisabled={selectedStoreUnavailable || !activePlans.length}
    >
      {selectedStoreUnavailable ? (
        <div className="rounded-2xl px-4 py-3 text-xs font-bold" style={scopeBadgeStyle('danger')}>
          La tienda esta inactiva. El backend puede rechazar nuevas suscripciones hasta reactivarla.
        </div>
      ) : null}

      <div className={formGridClass}>
        <div>
          <FieldLabel>Plan</FieldLabel>
          <SelectInput
            value={subscriptionForm.plan_id}
            onChange={(event) =>
              setSubscriptionForm((current) => ({ ...current, plan_id: event.target.value }))
            }
            required
          >
            <option value="">Selecciona un plan</option>
            {activePlans.map((plan) => (
              <option key={plan.public_id} value={plan.public_id}>
                {plan.name} · {formatCurrencyEsAr(plan.price, plan.currency)}
              </option>
            ))}
          </SelectInput>
        </div>
        <div>
          <FieldLabel>Status</FieldLabel>
          <SelectInput
            value={subscriptionForm.status}
            onChange={(event) =>
              setSubscriptionForm((current) => ({ ...current, status: event.target.value }))
            }
          >
            <option value="active">Activa</option>
            <option value="trialing">Prueba</option>
            <option value="past_due">Pago vencido</option>
            <option value="cancelled">Cancelada</option>
          </SelectInput>
        </div>
      </div>

      <div className={formGridClass}>
        <div>
          <FieldLabel>Monto base</FieldLabel>
          <TextInput
            type="number"
            min="0"
            step="0.01"
            value={subscriptionForm.base_amount}
            onChange={(event) =>
              setSubscriptionForm((current) => ({ ...current, base_amount: event.target.value }))
            }
            placeholder="Usa precio del plan si queda vacio"
          />
        </div>
        <div>
          <FieldLabel>Moneda</FieldLabel>
          <TextInput
            value={subscriptionForm.currency}
            onChange={(event) =>
              setSubscriptionForm((current) => ({
                ...current,
                currency: event.target.value.toUpperCase()
              }))
            }
          />
        </div>
      </div>

      <div className={formGridClass}>
        <div>
          <FieldLabel>Periodo desde</FieldLabel>
          <TextInput
            type="datetime-local"
            value={subscriptionForm.current_period_start}
            onChange={(event) =>
              setSubscriptionForm((current) => ({
                ...current,
                current_period_start: event.target.value
              }))
            }
          />
        </div>
        <div>
          <FieldLabel>Periodo hasta</FieldLabel>
          <TextInput
            type="datetime-local"
            value={subscriptionForm.current_period_end}
            onChange={(event) =>
              setSubscriptionForm((current) => ({
                ...current,
                current_period_end: event.target.value
              }))
            }
          />
        </div>
      </div>
    </SuperAdminFormModal>
  </>
)
