import React from "react";
import { User } from "@domain/entities/User";
import { Shield, User as UserIcon, Mail, Phone, CheckCircle2, XCircle, Edit2, Trash2 } from "lucide-react";
import { colors2000s, buttonStyles2000s } from "../../../theme/colors";

interface UserCardProps {
  user: User;
  onEdit: (user: User) => void;
  onDelete: (id: string) => void;
}

export const UserCard: React.FC<UserCardProps> = ({ user, onEdit, onDelete }) => {
  const isAdmin = user.role.isAdmin();
  
  const getInitials = (name: string) => {
    const parts = name.split(" ");
    const f = parts[0] ? parts[0][0] : "";
    const l = parts[1] ? parts[1][0] : "";
    return `${f}${l}`.toUpperCase() || "US";
  };

  const initials = getInitials(user.fullName);

  // Volumetric gradients and borders based on role
  const accentBorderColor = isAdmin ? "#3b82f6" : "#ff8c42";
  const avatarGradient = isAdmin 
    ? "linear-gradient(180deg, #3b82f6 0%, #2563eb 100%)" 
    : `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`;
  const avatarBorder = isAdmin ? "1px solid #2563eb" : `1px solid ${colors2000s.orange.accent}`;

  return (
    <div 
      className="relative p-6 rounded-[2rem] transition-all duration-200 hover:scale-[1.01] active:scale-[0.99] border-l-[6px] flex flex-col justify-between h-full"
      style={{
        background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
        borderTop: `1px solid ${colors2000s.border.default}`,
        borderRight: `1px solid ${colors2000s.border.default}`,
        borderBottom: `1px solid ${colors2000s.border.default}`,
        borderLeftColor: accentBorderColor,
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
            color: user.isActive ? '#10b981' : colors2000s.text.disabled
          }}
        >
          {user.isActive ? <CheckCircle2 size={12} className="text-emerald-500" /> : <XCircle size={12} className="text-gray-400" />}
          {user.isActive ? "ACTIVO" : "INACTIVO"}
        </span>
      </div>

      <div className="space-y-4 flex-1">
        {/* Header Section: Avatar initials + Titles */}
        <div className="flex items-center gap-4 pr-20">
          <div 
            className="w-12 h-12 rounded-full text-white flex items-center justify-center font-black text-sm shadow-md flex-shrink-0"
            style={{ 
              background: avatarGradient, 
              border: avatarBorder,
              boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
            }}
          >
            {initials}
          </div>
          <div className="min-w-0">
            <h3 className="font-black text-gray-800 text-sm uppercase tracking-tight truncate leading-tight">
              {user.fullName}
            </h3>
            <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mt-1 truncate">
              {user.email.getValue()}
            </p>
          </div>
        </div>

        {/* Badges/Rol */}
        <div className="flex flex-wrap gap-2 pt-1">
          <span 
            className="px-2.5 py-1 rounded-xl text-[9px] font-black border uppercase tracking-widest flex items-center gap-1"
            style={{
              background: 'white',
              border: `1px solid ${colors2000s.border.default}`,
              boxShadow: colors2000s.shadows.insetDark,
              color: isAdmin ? '#3b82f6' : colors2000s.orange.accent
            }}
          >
            {isAdmin ? <Shield size={10} /> : <UserIcon size={10} />}
            {user.role.getValue()}
          </span>
        </div>

        {/* Contact fields */}
        <div className="space-y-2 pt-2 border-t" style={{ borderColor: colors2000s.border.light }}>
          <div className="flex items-center gap-2 text-xs font-bold text-gray-500">
            <Mail size={14} className="text-gray-400" />
            <span className="truncate">{user.email.getValue()}</span>
          </div>
          {user.toPrimitives().phone && (
            <div className="flex items-center gap-2 text-xs font-bold text-gray-500">
              <Phone size={14} className="text-gray-400" />
              <span>{user.toPrimitives().phone}</span>
            </div>
          )}
        </div>
      </div>

      {/* Outlined Action Buttons in Footer */}
      <div className="grid grid-cols-2 gap-3 pt-4 border-t mt-4" style={{ borderColor: colors2000s.border.light }}>
        <button
          onClick={() => onEdit(user)}
          className="flex items-center justify-center gap-2 py-2.5 px-3 rounded-xl font-black text-[10px] uppercase tracking-widest transition-all active:scale-95"
          style={buttonStyles2000s.default}
        >
          <Edit2 size={14} /> Editar
        </button>
        <button
          onClick={() => onDelete(user.id)}
          className="flex items-center justify-center gap-2 py-2.5 px-3 rounded-xl font-black text-[10px] uppercase tracking-widest transition-all active:scale-95"
          style={{ ...buttonStyles2000s.default, color: '#ef4444' }}
        >
          <Trash2 size={14} /> Eliminar
        </button>
      </div>
    </div>
  );
};
