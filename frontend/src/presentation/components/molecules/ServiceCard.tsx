import React from "react";
import { Service } from "@domain/entities/Service";
import { Briefcase, Clock, DollarSign, Edit2, Trash2, CheckCircle2, XCircle } from "lucide-react";
import { colors2000s, buttonStyles2000s } from "../../../theme/colors";

interface ServiceCardProps {
  service: Service;
  onEdit: (service: Service) => void;
  onDelete: (id: string) => void;
  isSelected?: boolean;
}

export const ServiceCard: React.FC<ServiceCardProps> = ({
  service,
  onEdit,
  onDelete,
  isSelected = false,
}) => {
  const accentColor = service.color || "#FF6B35";

  return (
    <div 
      className={`relative p-6 rounded-[2rem] transition-all duration-200 hover:scale-[1.01] active:scale-[0.99] border-l-[6px] flex flex-col justify-between h-full ${
        isSelected ? "ring-2 ring-offset-2 ring-orange-400" : ""
      }`}
      style={{
        background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
        borderTop: `1px solid ${colors2000s.border.default}`,
        borderRight: `1px solid ${colors2000s.border.default}`,
        borderBottom: `1px solid ${colors2000s.border.default}`,
        borderLeftColor: accentColor,
        boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`
      }}
    >
      {/* Top right status badge */}
      <div className="absolute right-6 top-6">
        <span 
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-[9px] font-black uppercase tracking-widest"
          style={{ 
            background: 'white', 
            border: `1px solid ${colors2000s.border.default}`,
            boxShadow: colors2000s.shadows.insetDark,
            color: service.isActive ? '#10b981' : colors2000s.text.disabled
          }}
        >
          {service.isActive ? <CheckCircle2 size={12} className="text-emerald-500" /> : <XCircle size={12} className="text-gray-400" />}
          {service.isActive ? "ACTIVO" : "INACTIVO"}
        </span>
      </div>

      <div className="space-y-4 flex-1">
        {/* Header Section: Avatar initials + Titles */}
        <div className="flex items-center gap-4 pr-20">
          <div 
            className="w-12 h-12 rounded-2xl text-white flex items-center justify-center flex-shrink-0 shadow-md overflow-hidden"
            style={{ 
              background: `linear-gradient(180deg, ${accentColor} 0%, ${accentColor}dd 100%)`, 
              border: `1px solid ${accentColor}`,
              boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
            }}
          >
            {service.imageUrl ? (
              <img src={service.imageUrl} alt={service.name} className="w-full h-full object-cover" />
            ) : (
              <Briefcase size={22} className="text-white" />
            )}
          </div>
          <div className="min-w-0">
            <h3 className="font-black text-gray-800 text-sm uppercase tracking-tight truncate leading-tight">
              {service.name}
            </h3>
            <p className="text-[10px] font-bold text-gray-400 mt-1 truncate max-w-[200px] leading-tight">
              {service.description || "Sin descripción"}
            </p>
          </div>
        </div>

        {/* Specs metadata rows */}
        <div className="grid grid-cols-2 gap-4 pt-4 border-t" style={{ borderColor: colors2000s.border.light }}>
          {/* Duración */}
          <div 
            className="p-3 rounded-xl flex items-center gap-3 border"
            style={{
              background: 'white',
              borderColor: colors2000s.border.light,
              boxShadow: colors2000s.shadows.insetDark
            }}
          >
            <Clock size={16} className="text-gray-400" />
            <div>
              <p className="text-[8px] font-black text-gray-400 uppercase tracking-widest leading-none mb-1">Duración</p>
              <p className="text-xs font-black text-gray-800 leading-none">{service.duration.format()}</p>
            </div>
          </div>

          {/* Precio */}
          <div 
            className="p-3 rounded-xl flex items-center gap-3 border"
            style={{
              background: 'white',
              borderColor: colors2000s.border.light,
              boxShadow: colors2000s.shadows.insetDark
            }}
          >
            <DollarSign size={16} className="text-orange-500" />
            <div>
              <p className="text-[8px] font-black text-gray-400 uppercase tracking-widest leading-none mb-1">Precio</p>
              <p className="text-xs font-black leading-none" style={{ color: accentColor }}>
                ${service.price.getValue().toLocaleString()}
              </p>
            </div>
          </div>
        </div>
      </div>

      {/* Outlined Action Buttons in Footer */}
      <div className="grid grid-cols-2 gap-3 pt-4 border-t mt-5" style={{ borderColor: colors2000s.border.light }}>
        <button
          onClick={() => onEdit(service)}
          className="flex items-center justify-center gap-2 py-2.5 px-3 rounded-xl font-black text-[10px] uppercase tracking-widest transition-all active:scale-95"
          style={buttonStyles2000s.default}
        >
          <Edit2 size={14} /> Editar
        </button>
        <button
          onClick={() => onDelete(service.id)}
          className="flex items-center justify-center gap-2 py-2.5 px-3 rounded-xl font-black text-[10px] uppercase tracking-widest transition-all active:scale-95"
          style={{ ...buttonStyles2000s.default, color: '#ef4444' }}
        >
          <Trash2 size={14} /> Eliminar
        </button>
      </div>
    </div>
  );
};
