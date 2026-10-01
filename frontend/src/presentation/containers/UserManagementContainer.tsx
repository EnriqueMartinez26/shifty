import React, { useState } from 'react'

import { Plus, Loader2, User as UserIcon } from 'lucide-react'

import { User } from '@domain/entities/User'

import { getErrorMessage } from '@shared/errors/getErrorMessage'

import { colors2000s, buttonStyles2000s } from '../../theme/colors'
import { MessageBanner } from '../components/molecules/MessageBanner'
import { QueryErrorNotice } from '../components/molecules/QueryErrorNotice'
import { UserCard } from '../components/molecules/UserCard'
import { UserSearchForm } from '../components/molecules/UserSearchForm'
import { UserFormModal } from '../components/organisms/UserFormModal'
import { useAuth } from '../context/AuthContext'
import { useConfirm } from '../hooks/useConfirm'
import {
  useCreateManagedDomainUser,
  useDeleteManagedDomainUser,
  useManagedDomainUsers,
  useUpdateManagedDomainUser
} from '../hooks/useManagedDomainUsers'
import { canDeactivateUser, userFormRules } from '../lib/userAccessRules'
import { toCreateUserInput, toUserWriteInput } from '../lib/userFormPayload'
import { toUserListQuery } from '../lib/userSearch'
import type { UserFormValues } from '../types/forms'

/** Neutro (regla 20); el texto del backend no aclara que la baja es de otro admin. */
const USER_DELETE_ERRORS = {
  PERMISSION_DENIED: 'Solo el soporte global puede cambiar el acceso de otro administrador.'
}

export const UserManagementContainer: React.FC = () => {
  const { confirm, confirmDialog } = useConfirm()
  const { user: viewer } = useAuth()
  const [message, setMessage] = useState('')
  const [listQuery, setListQuery] = useState(() => toUserListQuery(''))
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)

  const {
    data: users,
    isLoading,
    error,
    hasNextPage,
    fetchNextPage,
    isFetchingNextPage
  } = useManagedDomainUsers(listQuery)
  const createMutation = useCreateManagedDomainUser()
  const updateMutation = useUpdateManagedDomainUser()
  const deleteMutation = useDeleteManagedDomainUser()

  const handleDelete = async (id: string) => {
    if (!(await confirm('¿Estás seguro de eliminar este usuario?'))) return
    // La baja es una desactivacion (soft delete). Con `mutate` un 403 o un
    // 400 se perdia en silencio: ahora se avisa.
    setMessage('')
    try {
      await deleteMutation.mutateAsync(id)
    } catch (err) {
      setMessage(getErrorMessage(err, 'No se pudo eliminar el usuario.', USER_DELETE_ERRORS))
    }
  }

  const handleEdit = (user: User) => {
    setEditingUser(user)
    setIsModalOpen(true)
  }

  const handleCreate = () => {
    setEditingUser(null)
    setIsModalOpen(true)
  }

  const handleFormSubmit = async (formData: UserFormValues) => {
    // El recorte de blancos y el diff del PATCH viven en userFormPayload
    // (FF-10): `''` en un nombre era un 422 del backend.
    if (editingUser) {
      await updateMutation.mutateAsync({
        id: editingUser.id,
        data: toUserWriteInput(formData, editingUser)
      })
    } else {
      await createMutation.mutateAsync(toCreateUserInput(formData))
    }
  }

  return (
    <div className="space-y-6">
      {confirmDialog}
      {/* Unified Skeuomorphic Header Card matching Reports.tsx */}
      <div
        className="flex flex-wrap gap-4 items-center justify-between p-6 rounded-lg"
        style={{
          background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
          border: `1px solid ${colors2000s.border.default}`,
          boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`
        }}
      >
        <div>
          <h2
            className="text-2xl font-black uppercase tracking-tight"
            style={{ color: colors2000s.text.primary }}
          >
            Gestión de Usuarios
          </h2>
          <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Administrá el equipo y los accesos del negocio.
          </p>
        </div>

        <button
          className="px-6 py-4 rounded-xl flex items-center gap-2 font-black uppercase tracking-widest text-xs transition-all active:scale-95 group"
          style={buttonStyles2000s.selected}
          onClick={handleCreate}
        >
          <Plus size={18} className="group-hover:rotate-90 transition-transform duration-300" />
          NUEVO USUARIO
        </button>
      </div>

      <UserSearchForm onSearch={(term) => setListQuery(toUserListQuery(term))} />

      <MessageBanner message={message} />

      <QueryErrorNotice error={error} message="No se pudieron cargar los usuarios." />

      {isLoading ? (
        <div
          className="flex flex-col items-center justify-center py-20 rounded-lg"
          style={{
            background: 'white',
            border: `1px solid ${colors2000s.border.light}`,
            boxShadow: colors2000s.shadows.insetDark
          }}
        >
          <Loader2
            className="w-12 h-12 animate-spin mb-4"
            style={{ color: colors2000s.orange.accent }}
          />
          <p
            className="text-xs font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            Cargando usuarios...
          </p>
        </div>
      ) : users?.length === 0 ? (
        <div
          className="flex flex-col items-center justify-center py-20 rounded-lg text-center"
          style={{
            background: 'white',
            border: `1px solid ${colors2000s.border.light}`,
            boxShadow: colors2000s.shadows.outer
          }}
        >
          <div
            className="w-20 h-20 rounded-md flex items-center justify-center mx-auto mb-6 shadow-inner"
            style={{ background: colors2000s.bg.disabled }}
          >
            <UserIcon
              size={40}
              className="opacity-25"
              style={{ color: colors2000s.text.primary }}
            />
          </div>
          <h3 className="text-xl font-black uppercase" style={{ color: colors2000s.text.primary }}>
            No se encontraron resultados
          </h3>
          <p
            className="text-xs font-bold max-w-xs mx-auto mt-2"
            style={{ color: colors2000s.text.secondary }}
          >
            Probá con otro término de búsqueda o agregá un nuevo usuario.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {users?.map((user) => (
            <UserCard
              key={user.id}
              user={user}
              onEdit={handleEdit}
              onDelete={(id) => void handleDelete(id)}
              canDelete={canDeactivateUser(viewer, user)}
            />
          ))}
        </div>
      )}

      {/* El servidor corta en `limit`: el resto llega por paginas (F4-03). */}
      {!isLoading && hasNextPage && (
        <button
          type="button"
          onClick={() => {
            void fetchNextPage()
          }}
          disabled={isFetchingNextPage}
          className="w-full px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest disabled:opacity-50"
          style={buttonStyles2000s.default}
        >
          {isFetchingNextPage ? 'Cargando...' : 'Ver más'}
        </button>
      )}

      {isModalOpen && (
        <UserFormModal
          key={editingUser?.id ?? 'new'}
          onClose={() => setIsModalOpen(false)}
          onSubmit={handleFormSubmit}
          editingUser={editingUser}
          rules={userFormRules(viewer, editingUser)}
        />
      )}
    </div>
  )
}
