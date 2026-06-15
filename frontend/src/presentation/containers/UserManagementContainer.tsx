import React, { useState } from 'react'

import { Plus, Search, Loader2, User as UserIcon } from 'lucide-react'

import { User } from '@domain/entities/User'

import { UserService } from '@application/services/UserService'

import { colors2000s, buttonStyles2000s } from '../../theme/colors'
import { UserCard } from '../components/molecules/UserCard'
import { UserFormModal } from '../components/organisms/UserFormModal'
import {
  useCreateManagedDomainUser,
  useDeleteManagedDomainUser,
  useManagedDomainUsers,
  useUpdateManagedDomainUser
} from '../hooks/useManagedDomainUsers'
import type { UserFormValues } from '../types/forms'

type UpdateUserInput = Parameters<UserService['updateUser']>[1]

export const UserManagementContainer: React.FC = () => {
  const [searchTerm, setSearchTerm] = useState('')
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)

  const { data: users, isLoading } = useManagedDomainUsers()
  const createMutation = useCreateManagedDomainUser()
  const updateMutation = useUpdateManagedDomainUser()
  const deleteMutation = useDeleteManagedDomainUser()

  const filteredUsers = users?.filter(
    (user) =>
      user.fullName.toLowerCase().includes(searchTerm.toLowerCase()) ||
      user.email.getValue().toLowerCase().includes(searchTerm.toLowerCase())
  )

  const handleDelete = (id: string) => {
    if (window.confirm('¿Estás seguro de eliminar este usuario?')) {
      deleteMutation.mutate(id)
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
    if (editingUser) {
      await updateMutation.mutateAsync({
        id: editingUser.id,
        data: formData as unknown as UpdateUserInput
      })
    } else {
      await createMutation.mutateAsync(formData)
    }
  }

  return (
    <div className="space-y-6">
      {/* Unified Skeuomorphic Header Card matching Reports.tsx */}
      <div
        className="flex flex-wrap gap-4 items-center justify-between p-6 rounded-3xl"
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

      {/* Unified Brand Styled Search Input */}
      <div className="relative group">
        <Search
          className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-orange-500 transition-colors"
          size={20}
        />
        <input
          type="text"
          placeholder="BUSCAR USUARIO..."
          className="w-full pl-12 pr-4 py-3.5 rounded-2xl font-black uppercase tracking-widest text-xs outline-none"
          style={{
            background: 'white',
            border: `1px solid ${colors2000s.border.default}`,
            boxShadow: colors2000s.shadows.insetDark,
            color: colors2000s.text.primary
          }}
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />
      </div>

      {isLoading ? (
        <div
          className="flex flex-col items-center justify-center py-20 rounded-[3rem]"
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
      ) : filteredUsers?.length === 0 ? (
        <div
          className="flex flex-col items-center justify-center py-20 rounded-[3rem] text-center"
          style={{
            background: 'white',
            border: `1px solid ${colors2000s.border.light}`,
            boxShadow: colors2000s.shadows.outer
          }}
        >
          <div
            className="w-20 h-20 rounded-2xl flex items-center justify-center mx-auto mb-6 shadow-inner"
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
          {filteredUsers?.map((user) => (
            <UserCard key={user.id} user={user} onEdit={handleEdit} onDelete={handleDelete} />
          ))}
        </div>
      )}

      <UserFormModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSubmit={handleFormSubmit}
        editingUser={editingUser}
      />
    </div>
  )
}
