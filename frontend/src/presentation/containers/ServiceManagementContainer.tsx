import React, { useState } from "react";
import { ServiceCard } from "../components/molecules/ServiceCard";
import { ServiceFormModal } from "../components/organisms/ServiceFormModal";
import { Service } from "@domain/entities/Service";
import { colors2000s, buttonStyles2000s } from "../../theme/colors";
import { Plus, Search, Loader2 } from "lucide-react";
import {
  useCreateManagedService,
  useDeleteManagedService,
  useManagedServices,
  useUpdateManagedService,
} from "../hooks/useManagedServices";

export const ServiceManagementContainer: React.FC = () => {
  const [searchTerm, setSearchTerm] = useState("");
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingService, setEditingService] = useState<Service | null>(null);

  const { data: services, isLoading } = useManagedServices();
  const createMutation = useCreateManagedService();
  const updateMutation = useUpdateManagedService();
  const deleteMutation = useDeleteManagedService();

  const filteredServices = services?.filter(service => 
    service.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  const handleDelete = (id: string) => {
    if (window.confirm("¿Estás seguro de eliminar este servicio? Esto no afectará turnos ya creados.")) {
      deleteMutation.mutate(id);
    }
  };

  const handleEdit = (service: Service) => {
    setEditingService(service);
    setIsModalOpen(true);
  };

  const handleCreate = () => {
    setEditingService(null);
    setIsModalOpen(true);
  };

  const handleFormSubmit = async (formData: any) => {
    if (editingService) {
      await updateMutation.mutateAsync({ id: editingService.id, data: formData });
    } else {
      await createMutation.mutateAsync(formData);
    }
  };

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
          <h2 className="text-2xl font-black uppercase tracking-tight" style={{ color: colors2000s.text.primary }}>
            Gestión de Servicios
          </h2>
          <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Configurá el catálogo de servicios de tu negocio.
          </p>
        </div>
        
        <button 
          className="px-6 py-4 rounded-xl flex items-center gap-2 font-black uppercase tracking-widest text-xs transition-all active:scale-95 group"
          style={buttonStyles2000s.selected}
          onClick={handleCreate}
        >
          <Plus size={18} className="group-hover:rotate-90 transition-transform duration-300" />
          NUEVO SERVICIO
        </button>
      </div>

      {/* Unified Brand Styled Search Input */}
      <div className="relative group">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-400 group-focus-within:text-[#FF6B35] transition-colors" size={20} />
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

      {isLoading ? (
        <div className="flex flex-col items-center justify-center py-20 gap-4">
          <Loader2 className="animate-spin text-orange-500" size={40} />
          <p className="text-gray-400 font-black uppercase text-xs tracking-widest">Cargando servicios...</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {filteredServices?.map(service => (
            <ServiceCard 
              key={service.id} 
              service={service} 
              onEdit={handleEdit}
              onDelete={handleDelete}
            />
          ))}
        </div>
      )}

      <ServiceFormModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSubmit={handleFormSubmit}
        editingService={editingService}
      />
    </div>
  );
};
