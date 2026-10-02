import React, { useState } from 'react'

import { Plus, Search, Loader2 } from 'lucide-react'

import { Service } from '@domain/entities/Service'

import { colors2000s, buttonStyles2000s } from '../../theme/colors'
import { QueryErrorNotice } from '../components/molecules/QueryErrorNotice'
import { ServiceCard } from '../components/molecules/ServiceCard'
import { ServiceFormModal } from '../components/organisms/ServiceFormModal'
import { useConfirm } from '../hooks/useConfirm'
import {
  useCreateManagedService,
  useDeleteManagedService,
  useManagedServiceCatalog,
  useRemoveServiceImage,
  useUpdateManagedService,
  useUploadServiceImage
} from '../hooks/useManagedServices'
import { useStoreWriteAccess } from '../hooks/useStoreWriteAccess'
import { notifyError } from '../lib/notify'
import type { ServiceFormValues } from '../types/forms'

export const ServiceManagementContainer: React.FC = () => {
  const { confirm, confirmDialog } = useConfirm()
  const [searchTerm, setSearchTerm] = useState('')
  const [isModalOpen, setIsModalOpen] = useState(false)
  const [editingService, setEditingService] = useState<Service | null>(null)

  // El catalogo trae los inactivos: "Eliminar" es un soft delete y sin ellos un
  // servicio borrado desaparecia sin forma de reactivarlo (FF-22).
  const { data: services, isLoading, error } = useManagedServiceCatalog()
  const createMutation = useCreateManagedService()
  const updateMutation = useUpdateManagedService()
  const deleteMutation = useDeleteManagedService()
  const uploadImageMutation = useUploadServiceImage()
  const removeImageMutation = useRemoveServiceImage()
  // Tienda suspendida (FF-15): POST, PATCH y DELETE /services/... (imagen
  // incluida) no estan en SUSPENSION_ALLOWED_WRITES y responden 402.
  const writeAccess = useStoreWriteAccess()
  const readOnlyReason = writeAccess.readOnly ? writeAccess.reason : null

  const filteredServices = services?.filter((service) =>
    service.name.toLowerCase().includes(searchTerm.toLowerCase())
  )

  const handleDelete = async (id: string) => {
    if (
      !(await confirm(
        '¿Estás seguro de eliminar este servicio? Esto no afectará turnos ya creados.'
      ))
    ) {
      return
    }
    // Sin este catch un borrado rechazado no decia nada (FF-17).
    try {
      await deleteMutation.mutateAsync(id)
    } catch (error: unknown) {
      notifyError(error, 'No se pudo eliminar el servicio.')
    }
  }

  const handleReactivate = async (id: string) => {
    try {
      await updateMutation.mutateAsync({ id, data: { isActive: true } })
    } catch (error: unknown) {
      notifyError(error, 'No se pudo reactivar el servicio.')
    }
  }

  const handleEdit = (service: Service) => {
    setEditingService(service)
    setIsModalOpen(true)
  }

  const handleCreate = () => {
    setEditingService(null)
    setIsModalOpen(true)
  }

  const handleFormSubmit = async (formData: ServiceFormValues) => {
    if (editingService) {
      // Sin cast: `ServiceFormValues` calza con `ServiceWriteInput`, asi que el
      // compilador verifica que lo que manda el formulario sea exactamente lo
      // que el payload de escritura sabe traducir (antes iba por
      // `as unknown as` y cualquier campo nuevo pasaba de largo en silencio).
      await updateMutation.mutateAsync({ id: editingService.id, data: formData })
    } else {
      await createMutation.mutateAsync(formData)
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
            Gestión de Servicios
          </h2>
          <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Configurá el catálogo de servicios de tu negocio.
          </p>
        </div>

        <button
          className="px-6 py-4 rounded-xl flex items-center gap-2 font-black uppercase tracking-widest text-xs transition-all active:scale-95 group disabled:opacity-50"
          style={buttonStyles2000s.selected}
          onClick={handleCreate}
          disabled={readOnlyReason !== null}
          title={readOnlyReason ?? undefined}
        >
          <Plus size={18} className="group-hover:rotate-90 transition-transform duration-300" />
          NUEVO SERVICIO
        </button>
      </div>

      {/* Unified Brand Styled Search Input */}
      <div className="relative group">
        <Search
          className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-[#FF6B35] transition-colors"
          size={20}
        />
        <input
          type="text"
          placeholder="BUSCAR SERVICIO..."
          className="w-full pl-12 pr-4 py-3.5 rounded-xl border text-xs font-black uppercase tracking-widest transition-all placeholder-gray-400"
          style={{
            background: 'white',
            borderColor: colors2000s.border.default,
            boxShadow: colors2000s.shadows.insetDark,
            color: colors2000s.text.primary,
            outline: 'none'
          }}
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
        />
      </div>

      <QueryErrorNotice error={error} message="No se pudieron cargar los servicios." />

      {isLoading ? (
        <div className="flex flex-col items-center justify-center py-20 gap-4">
          <Loader2 className="animate-spin text-orange-500" size={40} />
          <p className="text-gray-400 font-black uppercase text-xs tracking-widest">
            Cargando servicios...
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredServices?.map((service) => (
            <ServiceCard
              key={service.id}
              service={service}
              onEdit={handleEdit}
              onDelete={(id) => void handleDelete(id)}
              onReactivate={(id) => void handleReactivate(id)}
              readOnlyReason={readOnlyReason}
            />
          ))}
        </div>
      )}

      <ServiceFormModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSubmit={handleFormSubmit}
        editingService={editingService}
        onUploadImage={(id, file) => uploadImageMutation.mutateAsync({ id, file })}
        onRemoveImage={(id) => removeImageMutation.mutateAsync(id)}
        readOnlyReason={readOnlyReason}
      />
    </div>
  )
}
