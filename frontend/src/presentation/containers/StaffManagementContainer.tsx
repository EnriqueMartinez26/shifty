import React, { useState } from 'react'

import { Plus, User, Loader2, Search } from 'lucide-react'

import { Staff } from '@domain/entities/Staff'

import { colors2000s, buttonStyles2000s } from '../../theme/colors'
import { StaffCard } from '../components/molecules/StaffCard'
import { StaffFormModal } from '../components/organisms/StaffFormModal'
import {
  useCreateManagedStaff,
  useDeleteManagedStaff,
  useManagedStaff,
  useUpdateManagedStaff
} from '../hooks/useManagedStaff'

export const StaffManagementContainer: React.FC = () => {
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingStaff, setEditingStaff] = useState<Staff | null>(null)
  const [searchTerm, setSearchTerm] = useState('')

  const { data: staffList, isLoading } = useManagedStaff()
  const createMutation = useCreateManagedStaff()
  const updateMutation = useUpdateManagedStaff()
  const deleteMutation = useDeleteManagedStaff()

  const filteredStaff = staffList?.filter(
    (s) =>
      s.fullName.toLowerCase().includes(searchTerm.toLowerCase()) ||
      s.displayName.toLowerCase().includes(searchTerm.toLowerCase())
  )

  return (
    <div className="space-y-6 animate-in fade-in duration-700">
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
            Staff & Profesionales
          </h2>
          <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Gestioná tu equipo y sus especialidades.
          </p>
        </div>

        <button
          className="px-6 py-4 rounded-xl flex items-center gap-2 font-black uppercase tracking-widest text-xs transition-all active:scale-95 group"
          style={buttonStyles2000s.selected}
          onClick={() => {
            setEditingStaff(null)
            setIsModalOpen(true)
          }}
        >
          <Plus size={18} className="group-hover:rotate-90 transition-transform duration-300" />
          NUEVO PROFESIONAL
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
          placeholder="BUSCAR PROFESIONAL..."
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
            Sincronizando equipo...
          </p>
        </div>
      ) : filteredStaff?.length === 0 ? (
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
            <User size={40} className="opacity-25" style={{ color: colors2000s.text.primary }} />
          </div>
          <h3 className="text-xl font-black uppercase" style={{ color: colors2000s.text.primary }}>
            No se encontraron resultados
          </h3>
          <p
            className="text-xs font-bold max-w-xs mx-auto mt-2"
            style={{ color: colors2000s.text.secondary }}
          >
            Probá con otro término de búsqueda o agregá un nuevo profesional.
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredStaff?.map((staff) => (
            <StaffCard
              key={staff.id}
              staff={staff}
              onEdit={(s) => {
                setEditingStaff(s)
                setIsModalOpen(true)
              }}
              onDelete={(id) => {
                if (window.confirm('¿Estás seguro de eliminar a este profesional?')) {
                  deleteMutation.mutate(id)
                }
              }}
            />
          ))}
        </div>
      )}

      <StaffFormModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        editingStaff={editingStaff}
        onSubmit={async (data) => {
          if (editingStaff) {
            await updateMutation.mutateAsync({ id: editingStaff.id, data })
          } else {
            await createMutation.mutateAsync(data)
          }
        }}
      />
    </div>
  )
}
