import React from 'react'

import { colors2000s } from '../../../theme/colors'
import { SuperAdminFormModal } from '../../components/organisms/SuperAdminFormModal'
import { FieldLabel, SelectInput, TextInput, ToggleRow } from '../SuperAdminUi'
import {
  formGridClass,
  innerCardStyle,
  type PendingState,
  type SuperAdminModalKey,
  type UserFormState
} from './shared'

/**
 * Modales del panel SuperAdmin, agrupados por dominio.
 *
 * El estado y los handlers siguen viviendo en SuperAdmin.tsx (el contenedor);
 * estos componentes son presentacionales: reciben todo por props con los
 * mismos nombres para que el JSX movido quede identico al original.
 */

interface UserModalsProps {
  modal: SuperAdminModalKey
  closeModal: () => void
  modalError: string | null
  userForm: UserFormState
  setUserForm: React.Dispatch<React.SetStateAction<UserFormState>>
  handleUserSubmit: (event: React.FormEvent<HTMLFormElement>) => Promise<void>
  updateUserMutation: PendingState
}

export const UserModals: React.FC<UserModalsProps> = ({
  modal,
  closeModal,
  modalError,
  userForm,
  setUserForm,
  handleUserSubmit,
  updateUserMutation
}) => (
  <>
    <SuperAdminFormModal
      isOpen={modal === 'edit-user'}
      onClose={closeModal}
      onSubmit={handleUserSubmit}
      title="Editar usuario"
      subtitle="Actualiza rol, datos de contacto y estado del usuario seleccionado."
      submitLabel="Guardar usuario"
      loading={updateUserMutation.isPending}
      error={modalError}
    >
      <div
        className="rounded-2xl px-4 py-3 text-xs font-bold"
        style={{ ...innerCardStyle, color: colors2000s.text.secondary }}
      >
        Email de acceso:{' '}
        <span style={{ color: colors2000s.text.primary }}>{userForm.email || 'Sin email'}</span>
      </div>

      <div className={formGridClass}>
        <div>
          <FieldLabel>Nombre</FieldLabel>
          <TextInput
            value={userForm.first_name}
            onChange={(event) =>
              setUserForm((current) => ({ ...current, first_name: event.target.value }))
            }
          />
        </div>
        <div>
          <FieldLabel>Apellido</FieldLabel>
          <TextInput
            value={userForm.last_name}
            onChange={(event) =>
              setUserForm((current) => ({ ...current, last_name: event.target.value }))
            }
          />
        </div>
      </div>

      <div className={formGridClass}>
        <div>
          <FieldLabel>Rol</FieldLabel>
          <SelectInput
            value={userForm.role}
            onChange={(event) =>
              setUserForm((current) => ({
                ...current,
                role: event.target.value as UserFormState['role']
              }))
            }
          >
            <option value="admin">Admin</option>
            <option value="staff">Profesional</option>
            <option value="receptionist">Recepcion</option>
            <option value="client">Cliente</option>
          </SelectInput>
        </div>
        <div>
          <FieldLabel>Telefono</FieldLabel>
          <TextInput
            value={userForm.phone}
            onChange={(event) =>
              setUserForm((current) => ({ ...current, phone: event.target.value }))
            }
          />
        </div>
      </div>

      <div>
        <FieldLabel>Nueva password (opcional)</FieldLabel>
        <TextInput
          type="password"
          value={userForm.password}
          onChange={(event) =>
            setUserForm((current) => ({ ...current, password: event.target.value }))
          }
          minLength={8}
        />
      </div>

      <ToggleRow
        label="Usuario activo"
        description="Mantiene o revoca su acceso dentro del tenant."
        checked={userForm.is_active}
        onToggle={() => setUserForm((current) => ({ ...current, is_active: !current.is_active }))}
      />
    </SuperAdminFormModal>
  </>
)
