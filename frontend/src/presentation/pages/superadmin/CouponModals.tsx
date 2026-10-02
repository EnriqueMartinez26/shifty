import React from 'react'

import type { SuperAdminCoupon, SuperAdminStoreRow } from '@application/services/SuperAdminService'

import { formatCurrency } from '@shared/utils/currency'

import {
  formGridClass,
  innerCardStyle,
  scopeBadgeStyle,
  type CouponFormState,
  type PendingState,
  type RedeemFormState,
  type SuperAdminModalKey
} from './shared'
import { colors2000s } from '../../../theme/colors'
import { SuperAdminFormModal } from '../../components/organisms/SuperAdminFormModal'
import { FieldLabel, SelectInput, TextArea, TextInput, ToggleRow } from '../SuperAdminUi'

/**
 * Modales del panel SuperAdmin, agrupados por dominio.
 *
 * El estado y los handlers siguen viviendo en SuperAdmin.tsx (el contenedor);
 * estos componentes son presentacionales: reciben todo por props con los
 * mismos nombres para que el JSX movido quede identico al original.
 */

interface CouponModalsProps {
  modal: SuperAdminModalKey
  closeModal: () => void
  modalError: string | null
  selectedStore: SuperAdminStoreRow | null
  hasSelectedStoreSubscription: boolean
  activeCoupons: SuperAdminCoupon[]
  couponForm: CouponFormState
  setCouponForm: React.Dispatch<React.SetStateAction<CouponFormState>>
  handleCouponSubmit: (event: React.FormEvent<HTMLFormElement>) => Promise<void>
  createCouponMutation: PendingState
  updateCouponMutation: PendingState
  redeemForm: RedeemFormState
  setRedeemForm: React.Dispatch<React.SetStateAction<RedeemFormState>>
  handleRedeemSubmit: (event: React.FormEvent<HTMLFormElement>) => Promise<void>
  redeemCouponMutation: PendingState
}

export const CouponModals: React.FC<CouponModalsProps> = ({
  modal,
  closeModal,
  modalError,
  selectedStore,
  hasSelectedStoreSubscription,
  activeCoupons,
  couponForm,
  setCouponForm,
  handleCouponSubmit,
  createCouponMutation,
  updateCouponMutation,
  redeemForm,
  setRedeemForm,
  handleRedeemSubmit,
  redeemCouponMutation
}) => (
  <>
    <SuperAdminFormModal
      isOpen={modal === 'create-coupon' || modal === 'edit-coupon'}
      onClose={closeModal}
      onSubmit={handleCouponSubmit}
      title={modal === 'create-coupon' ? 'Crear cupón' : 'Editar cupón'}
      subtitle="Gestiona valor, vigencia, cupo y reglas de canje global."
      submitLabel={modal === 'create-coupon' ? 'Crear cupón' : 'Guardar cupón'}
      loading={createCouponMutation.isPending || updateCouponMutation.isPending}
      error={modalError}
    >
      <div className={formGridClass}>
        <div>
          <FieldLabel>Código</FieldLabel>
          <TextInput
            value={couponForm.code}
            onChange={(event) =>
              setCouponForm((current) => ({ ...current, code: event.target.value.toUpperCase() }))
            }
            required
          />
        </div>
        <div>
          <FieldLabel>Tipo</FieldLabel>
          <SelectInput
            value={couponForm.coupon_type}
            onChange={(event) =>
              setCouponForm((current) => ({
                ...current,
                coupon_type: event.target.value as CouponFormState['coupon_type']
              }))
            }
          >
            <option value="percent">Porcentaje</option>
            <option value="fixed">Monto fijo</option>
          </SelectInput>
        </div>
      </div>

      <div className={formGridClass}>
        <div>
          <FieldLabel>Valor</FieldLabel>
          <TextInput
            type="number"
            min="0"
            step="0.01"
            value={couponForm.value}
            onChange={(event) =>
              setCouponForm((current) => ({ ...current, value: event.target.value }))
            }
            required
          />
        </div>
        <div>
          <FieldLabel>Moneda</FieldLabel>
          <TextInput
            value={couponForm.currency}
            onChange={(event) =>
              setCouponForm((current) => ({
                ...current,
                currency: event.target.value.toUpperCase()
              }))
            }
            disabled={couponForm.coupon_type === 'percent'}
          />
        </div>
      </div>

      <div className={formGridClass}>
        <div>
          <FieldLabel>Max usos</FieldLabel>
          <TextInput
            type="number"
            min="1"
            value={couponForm.max_uses}
            onChange={(event) =>
              setCouponForm((current) => ({ ...current, max_uses: event.target.value }))
            }
            placeholder="Sin límite"
          />
        </div>
        <div>
          <FieldLabel>Canje único por tienda</FieldLabel>
          <SelectInput
            value={couponForm.one_time_per_store ? 'yes' : 'no'}
            onChange={(event) =>
              setCouponForm((current) => ({
                ...current,
                one_time_per_store: event.target.value === 'yes'
              }))
            }
          >
            <option value="yes">Si</option>
            <option value="no">No</option>
          </SelectInput>
        </div>
      </div>

      <div className={formGridClass}>
        <div>
          <FieldLabel>Vigente desde</FieldLabel>
          <TextInput
            type="datetime-local"
            value={couponForm.valid_from}
            onChange={(event) =>
              setCouponForm((current) => ({ ...current, valid_from: event.target.value }))
            }
          />
        </div>
        <div>
          <FieldLabel>Vigente hasta</FieldLabel>
          <TextInput
            type="datetime-local"
            value={couponForm.valid_until}
            onChange={(event) =>
              setCouponForm((current) => ({ ...current, valid_until: event.target.value }))
            }
          />
        </div>
      </div>

      <div>
        <FieldLabel>Descripción</FieldLabel>
        <TextArea
          value={couponForm.description}
          onChange={(event) =>
            setCouponForm((current) => ({ ...current, description: event.target.value }))
          }
        />
      </div>

      {modal === 'edit-coupon' ? (
        <ToggleRow
          label="Cupón activo"
          description="Definí si se puede seguir canjeando."
          checked={couponForm.is_active}
          onToggle={() =>
            setCouponForm((current) => ({ ...current, is_active: !current.is_active }))
          }
        />
      ) : null}
    </SuperAdminFormModal>

    <SuperAdminFormModal
      isOpen={modal === 'redeem-coupon'}
      onClose={closeModal}
      onSubmit={handleRedeemSubmit}
      title="Canjear cupón"
      subtitle={selectedStore ? `Aplicar descuento a ${selectedStore.name}` : 'Canje sobre tienda'}
      submitLabel="Canjear cupón"
      loading={redeemCouponMutation.isPending}
      error={modalError}
      submitDisabled={!selectedStore || !hasSelectedStoreSubscription || !activeCoupons.length}
    >
      {!hasSelectedStoreSubscription ? (
        <div className="rounded-2xl px-4 py-3 text-xs font-bold" style={scopeBadgeStyle('danger')}>
          Esta tienda no tiene suscripción activa. No se puede canjear un cupón todavía.
        </div>
      ) : null}

      <div>
        <FieldLabel>Cupón</FieldLabel>
        <SelectInput
          value={redeemForm.coupon_code}
          onChange={(event) => setRedeemForm({ coupon_code: event.target.value })}
          required
        >
          <option value="">Seleccioná un cupón</option>
          {activeCoupons.map((coupon) => (
            <option key={coupon.public_id} value={coupon.code}>
              {coupon.code} ·{' '}
              {coupon.coupon_type === 'percent'
                ? `${coupon.value}%`
                : formatCurrency(coupon.value, coupon.currency || 'ARS')}
            </option>
          ))}
        </SelectInput>
      </div>

      <div
        className="rounded-2xl px-4 py-3 text-xs font-bold"
        style={{ ...innerCardStyle, color: colors2000s.text.secondary }}
      >
        Antes de confirmar el canje se valida que la tienda esté activa, la suscripción vigente, el
        cupón sin vencer y el máximo de usos.
      </div>
    </SuperAdminFormModal>
  </>
)
