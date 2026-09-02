import React from 'react'

import type { SuperAdminCoupon, SuperAdminStoreRow } from '@application/services/SuperAdminService'

import { colors2000s } from '../../../theme/colors'
import { SuperAdminFormModal } from '../../components/organisms/SuperAdminFormModal'
import { formatCurrencyEsAr } from '../../lib/formatters'
import { FieldLabel, SelectInput, TextArea, TextInput, ToggleRow } from '../SuperAdminUi'
import {
  formGridClass,
  innerCardStyle,
  scopeBadgeStyle,
  type CouponFormState,
  type PendingState,
  type RedeemFormState,
  type SuperAdminModalKey
} from './shared'

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
      title={modal === 'create-coupon' ? 'Crear cupon' : 'Editar cupon'}
      subtitle="Gestiona valor, vigencia, cupo y reglas de canje global."
      submitLabel={modal === 'create-coupon' ? 'Crear cupon' : 'Guardar cupon'}
      loading={createCouponMutation.isPending || updateCouponMutation.isPending}
      error={modalError}
    >
      <div className={formGridClass}>
        <div>
          <FieldLabel>Codigo</FieldLabel>
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
            placeholder="Sin limite"
          />
        </div>
        <div>
          <FieldLabel>Canje unico por tienda</FieldLabel>
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
        <FieldLabel>Descripcion</FieldLabel>
        <TextArea
          value={couponForm.description}
          onChange={(event) =>
            setCouponForm((current) => ({ ...current, description: event.target.value }))
          }
        />
      </div>

      {modal === 'edit-coupon' ? (
        <ToggleRow
          label="Cupon activo"
          description="Define si puede seguir canjeandose."
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
      title="Canjear cupon"
      subtitle={selectedStore ? `Aplicar descuento a ${selectedStore.name}` : 'Canje sobre tienda'}
      submitLabel="Canjear cupon"
      loading={redeemCouponMutation.isPending}
      error={modalError}
      submitDisabled={!selectedStore || !hasSelectedStoreSubscription || !activeCoupons.length}
    >
      {!hasSelectedStoreSubscription ? (
        <div className="rounded-2xl px-4 py-3 text-xs font-bold" style={scopeBadgeStyle('danger')}>
          Esta tienda no tiene suscripcion activa. No se puede canjear un cupon todavia.
        </div>
      ) : null}

      <div>
        <FieldLabel>Cupon</FieldLabel>
        <SelectInput
          value={redeemForm.coupon_code}
          onChange={(event) => setRedeemForm({ coupon_code: event.target.value })}
          required
        >
          <option value="">Selecciona un cupon</option>
          {activeCoupons.map((coupon) => (
            <option key={coupon.public_id} value={coupon.code}>
              {coupon.code} ·{' '}
              {coupon.coupon_type === 'percent'
                ? `${coupon.value}%`
                : formatCurrencyEsAr(coupon.value, coupon.currency || 'ARS')}
            </option>
          ))}
        </SelectInput>
      </div>

      <div
        className="rounded-2xl px-4 py-3 text-xs font-bold"
        style={{ ...innerCardStyle, color: colors2000s.text.secondary }}
      >
        El backend valida tienda activa, suscripcion vigente, expiracion del cupon y maximo de usos
        antes de confirmar el canje.
      </div>
    </SuperAdminFormModal>
  </>
)
