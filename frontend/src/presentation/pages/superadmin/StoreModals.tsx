import React from 'react'

import { PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH } from '@domain/value-objects/PasswordRules'

import type { SuperAdminStoreRow } from '@application/services/SuperAdminService'

import { SuperAdminFormModal } from '../../components/organisms/SuperAdminFormModal'
import { FieldLabel, TextInput, ToggleRow } from '../SuperAdminUi'
import {
  formGridClass,
  storeScopedTitle,
  type AdminFormState,
  type PendingState,
  type StoreFormState,
  type SuperAdminModalKey
} from './shared'

/**
 * Modales del panel SuperAdmin, agrupados por dominio.
 *
 * El estado y los handlers siguen viviendo en SuperAdmin.tsx (el contenedor);
 * estos componentes son presentacionales: reciben todo por props con los
 * mismos nombres para que el JSX movido quede identico al original.
 */

interface StoreModalsProps {
  modal: SuperAdminModalKey
  closeModal: () => void
  modalError: string | null
  selectedStore: SuperAdminStoreRow | null
  storeForm: StoreFormState
  setStoreForm: React.Dispatch<React.SetStateAction<StoreFormState>>
  handleStoreSubmit: (event: React.FormEvent<HTMLFormElement>) => Promise<void>
  createStoreMutation: PendingState
  updateStoreMutation: PendingState
  adminForm: AdminFormState
  setAdminForm: React.Dispatch<React.SetStateAction<AdminFormState>>
  handleAdminSubmit: (event: React.FormEvent<HTMLFormElement>) => Promise<void>
  createAdminMutation: PendingState
}

export const StoreModals: React.FC<StoreModalsProps> = ({
  modal,
  closeModal,
  modalError,
  selectedStore,
  storeForm,
  setStoreForm,
  handleStoreSubmit,
  createStoreMutation,
  updateStoreMutation,
  adminForm,
  setAdminForm,
  handleAdminSubmit,
  createAdminMutation
}) => (
  <>
    <SuperAdminFormModal
      isOpen={modal === 'create-store' || modal === 'edit-store'}
      onClose={closeModal}
      onSubmit={handleStoreSubmit}
      title={
        modal === 'create-store'
          ? 'Crear tienda'
          : storeScopedTitle('Editar tienda', null, selectedStore)
      }
      subtitle="Definí la identidad de la tienda, sus reglas de operación y las notificaciones base."
      submitLabel={modal === 'create-store' ? 'Crear tienda' : 'Guardar tienda'}
      loading={createStoreMutation.isPending || updateStoreMutation.isPending}
      error={modalError}
    >
      <div className={formGridClass}>
        <div>
          <FieldLabel htmlFor="store-name">Nombre</FieldLabel>
          <TextInput
            id="store-name"
            value={storeForm.name}
            onChange={(event) =>
              setStoreForm((current) => ({ ...current, name: event.target.value }))
            }
            required
          />
        </div>
        <div>
          <FieldLabel htmlFor="store-slug">Slug</FieldLabel>
          <TextInput
            id="store-slug"
            value={storeForm.slug}
            onChange={(event) =>
              setStoreForm((current) => ({ ...current, slug: event.target.value }))
            }
            required
          />
        </div>
      </div>

      <div className={formGridClass}>
        <div>
          <FieldLabel htmlFor="store-primary-color-picker">Color principal</FieldLabel>
          <div className="flex gap-3">
            <TextInput
              id="store-primary-color-picker"
              type="color"
              value={storeForm.primary_color}
              onChange={(event) =>
                setStoreForm((current) => ({ ...current, primary_color: event.target.value }))
              }
              className="h-12 w-20 p-2"
            />
            <label className="sr-only" htmlFor="store-primary-color-hex">
              Código hexadecimal del color principal
            </label>
            <TextInput
              id="store-primary-color-hex"
              value={storeForm.primary_color}
              onChange={(event) =>
                setStoreForm((current) => ({ ...current, primary_color: event.target.value }))
              }
            />
          </div>
        </div>
        {/* Sin logo: lo sube la tienda desde su panel; la CSP de produccion no
            carga una URL de otro sitio. */}
      </div>

      <div className={formGridClass}>
        <div>
          <FieldLabel htmlFor="store-cancellation-hours">Horas de cancelación</FieldLabel>
          <TextInput
            id="store-cancellation-hours"
            type="number"
            min="0"
            value={storeForm.cancellation_hours}
            onChange={(event) =>
              setStoreForm((current) => ({ ...current, cancellation_hours: event.target.value }))
            }
            required
          />
        </div>
        <div>
          <FieldLabel htmlFor="store-buffer-minutes">Buffer (minutos)</FieldLabel>
          <TextInput
            id="store-buffer-minutes"
            type="number"
            min="0"
            value={storeForm.buffer_minutes}
            onChange={(event) =>
              setStoreForm((current) => ({ ...current, buffer_minutes: event.target.value }))
            }
            required
          />
        </div>
      </div>

      <div className="grid gap-3">
        <ToggleRow
          label="Confirmaciones por email"
          description="Controla si la tienda envía la confirmación de reserva."
          checked={storeForm.send_email_confirmation}
          onToggle={() =>
            setStoreForm((current) => ({
              ...current,
              send_email_confirmation: !current.send_email_confirmation
            }))
          }
        />
        <ToggleRow
          label="Recordatorios por email"
          description="Controla si la tienda envía recordatorios automáticos."
          checked={storeForm.send_email_reminders}
          onToggle={() =>
            setStoreForm((current) => ({
              ...current,
              send_email_reminders: !current.send_email_reminders
            }))
          }
        />
        {modal === 'edit-store' ? (
          <ToggleRow
            label="Tienda activa"
            description="Desactivarla bloquea la operación de la tienda."
            checked={storeForm.is_active}
            onToggle={() =>
              setStoreForm((current) => ({ ...current, is_active: !current.is_active }))
            }
          />
        ) : null}
      </div>
    </SuperAdminFormModal>

    <SuperAdminFormModal
      isOpen={modal === 'create-admin'}
      onClose={closeModal}
      onSubmit={handleAdminSubmit}
      title={storeScopedTitle('Crear admin', 'en', selectedStore)}
      subtitle={selectedStore ? `Nuevo admin para ${selectedStore.name}` : 'Nuevo admin de tienda'}
      submitLabel="Crear admin"
      loading={createAdminMutation.isPending}
      error={modalError}
    >
      <div className={formGridClass}>
        <div>
          <FieldLabel htmlFor="admin-first-name">Nombre</FieldLabel>
          <TextInput
            id="admin-first-name"
            value={adminForm.first_name}
            onChange={(event) =>
              setAdminForm((current) => ({ ...current, first_name: event.target.value }))
            }
            required
          />
        </div>
        <div>
          <FieldLabel htmlFor="admin-last-name">Apellido</FieldLabel>
          <TextInput
            id="admin-last-name"
            value={adminForm.last_name}
            onChange={(event) =>
              setAdminForm((current) => ({ ...current, last_name: event.target.value }))
            }
            required
          />
        </div>
      </div>

      <div className={formGridClass}>
        <div>
          <FieldLabel htmlFor="admin-email">Email</FieldLabel>
          <TextInput
            id="admin-email"
            type="email"
            value={adminForm.email}
            onChange={(event) =>
              setAdminForm((current) => ({ ...current, email: event.target.value }))
            }
            required
          />
        </div>
        <div>
          <FieldLabel htmlFor="admin-phone">Teléfono</FieldLabel>
          <TextInput
            id="admin-phone"
            value={adminForm.phone}
            onChange={(event) =>
              setAdminForm((current) => ({ ...current, phone: event.target.value }))
            }
          />
        </div>
      </div>

      <div>
        <FieldLabel htmlFor="admin-password">Password</FieldLabel>
        <TextInput
          id="admin-password"
          type="password"
          value={adminForm.password}
          onChange={(event) =>
            setAdminForm((current) => ({ ...current, password: event.target.value }))
          }
          autoComplete="new-password"
          minLength={PASSWORD_MIN_LENGTH}
          maxLength={PASSWORD_MAX_LENGTH * 2}
          required
        />
      </div>
    </SuperAdminFormModal>
  </>
)
