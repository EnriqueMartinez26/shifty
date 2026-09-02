import React from 'react'

import type { SuperAdminStoreRow } from '@application/services/SuperAdminService'

import { SuperAdminFormModal } from '../../components/organisms/SuperAdminFormModal'
import { FieldLabel, TextInput, ToggleRow } from '../SuperAdminUi'
import {
  formGridClass,
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
      title={modal === 'create-store' ? 'Crear tienda' : 'Editar tienda'}
      subtitle="Define identidad del tenant, reglas de operacion y notificaciones base."
      submitLabel={modal === 'create-store' ? 'Crear tienda' : 'Guardar tienda'}
      loading={createStoreMutation.isPending || updateStoreMutation.isPending}
      error={modalError}
    >
      <div className={formGridClass}>
        <div>
          <FieldLabel>Nombre</FieldLabel>
          <TextInput
            value={storeForm.name}
            onChange={(event) =>
              setStoreForm((current) => ({ ...current, name: event.target.value }))
            }
            required
          />
        </div>
        <div>
          <FieldLabel>Slug</FieldLabel>
          <TextInput
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
          <FieldLabel>Color principal</FieldLabel>
          <div className="flex gap-3">
            <TextInput
              type="color"
              value={storeForm.primary_color}
              onChange={(event) =>
                setStoreForm((current) => ({ ...current, primary_color: event.target.value }))
              }
              className="h-12 w-20 p-2"
            />
            <TextInput
              value={storeForm.primary_color}
              onChange={(event) =>
                setStoreForm((current) => ({ ...current, primary_color: event.target.value }))
              }
            />
          </div>
        </div>
        <div>
          <FieldLabel>Logo URL</FieldLabel>
          <TextInput
            value={storeForm.logo_url}
            onChange={(event) =>
              setStoreForm((current) => ({ ...current, logo_url: event.target.value }))
            }
            placeholder="https://..."
          />
        </div>
      </div>

      <div className={formGridClass}>
        <div>
          <FieldLabel>Horas de cancelacion</FieldLabel>
          <TextInput
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
          <FieldLabel>Buffer (minutos)</FieldLabel>
          <TextInput
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
          description="Controla si el tenant envia confirmacion de reserva."
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
          description="Controla si el tenant envia recordatorios automaticos."
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
            description="Desactivar bloquea el contexto operativo del tenant."
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
      title="Crear admin"
      subtitle={selectedStore ? `Nuevo admin para ${selectedStore.name}` : 'Nuevo admin de tienda'}
      submitLabel="Crear admin"
      loading={createAdminMutation.isPending}
      error={modalError}
    >
      <div className={formGridClass}>
        <div>
          <FieldLabel>Nombre</FieldLabel>
          <TextInput
            value={adminForm.first_name}
            onChange={(event) =>
              setAdminForm((current) => ({ ...current, first_name: event.target.value }))
            }
            required
          />
        </div>
        <div>
          <FieldLabel>Apellido</FieldLabel>
          <TextInput
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
          <FieldLabel>Email</FieldLabel>
          <TextInput
            type="email"
            value={adminForm.email}
            onChange={(event) =>
              setAdminForm((current) => ({ ...current, email: event.target.value }))
            }
            required
          />
        </div>
        <div>
          <FieldLabel>Telefono</FieldLabel>
          <TextInput
            value={adminForm.phone}
            onChange={(event) =>
              setAdminForm((current) => ({ ...current, phone: event.target.value }))
            }
          />
        </div>
      </div>

      <div>
        <FieldLabel>Password</FieldLabel>
        <TextInput
          type="password"
          value={adminForm.password}
          onChange={(event) =>
            setAdminForm((current) => ({ ...current, password: event.target.value }))
          }
          minLength={8}
          required
        />
      </div>
    </SuperAdminFormModal>
  </>
)
