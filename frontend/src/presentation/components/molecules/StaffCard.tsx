import React from 'react'

import { Mail, Edit3, Trash2, CheckCircle2, XCircle } from 'lucide-react'

import { Staff } from '@domain/entities/Staff'

import { colors2000s, buttonStyles2000s } from '../../../theme/colors'

interface StaffCardProps {
  staff: Staff
  onEdit: (staff: Staff) => void
  onDelete: (id: string) => void
}

export const StaffCard: React.FC<StaffCardProps> = ({ staff, onEdit, onDelete }) => {
  const getInitials = (first: string, last: string) => {
    const f = first ? first[0] : ''
    const l = last ? last[0] : ''
    return `${f}${l}`.toUpperCase() || 'ST'
  }

  const initials = getInitials(staff.firstName, staff.lastName)
  const isAdmin = staff.role === 'ADMIN'

  // Volumetric gradients and borders based on role
  const accentBorderColor = isAdmin ? '#3b82f6' : '#ff8c42'
  const avatarGradient = isAdmin
    ? 'linear-gradient(180deg, #3b82f6 0%, #2563eb 100%)'
    : `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`
  const avatarBorder = isAdmin ? '1px solid #2563eb' : `1px solid ${colors2000s.orange.accent}`

  return (
    <div
      className="relative p-6 rounded-[2rem] transition-all duration-200 hover:scale-[1.01] active:scale-[0.99] border-l-[6px]"
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
            color: staff.isActive ? '#10b981' : colors2000s.text.disabled
          }}
        >
          {staff.isActive ? (
            <CheckCircle2 size={12} className="text-emerald-500" />
          ) : (
            <XCircle size={12} className="text-gray-400" />
          )}
          {staff.isActive ? 'ACTIVO' : 'INACTIVO'}
        </span>
      </div>

      <div className="space-y-4">
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
              {staff.displayName}
            </h3>
            <p className="text-[10px] font-black text-gray-400 uppercase tracking-widest mt-1 truncate">
              {staff.fullName}
            </p>
          </div>
        </div>

        {/* Email contact field */}
        <div className="flex items-center gap-2 text-xs font-bold text-gray-500 pt-1">
          <Mail size={14} className="text-gray-400" />
          <span className="truncate">{staff.email.getValue()}</span>
        </div>

        {/* Metadata Specialties Section */}
        <div
          className="flex items-center gap-2 pt-3 border-t"
          style={{ borderColor: colors2000s.border.light }}
        >
          <span className="text-[9px] font-black uppercase tracking-widest text-gray-400">
            Servicios:
          </span>
          <div className="flex flex-wrap gap-1">
            {(staff.serviceIds || []).length === 0 ? (
              <span className="text-[9px] font-bold text-gray-400 italic">Sin servicios</span>
            ) : (
              (staff.serviceIds || []).slice(0, 3).map((id, index) => (
                <span
                  key={id}
                  className="px-2 py-0.5 rounded text-[8px] font-black border uppercase tracking-widest"
                  style={{
                    background: 'white',
                    border: `1px solid ${colors2000s.border.default}`,
                    boxShadow: colors2000s.shadows.insetDark,
                    color: colors2000s.orange.accent
                  }}
                >
                  S-{index + 1}
                </span>
              ))
            )}
            {(staff.serviceIds || []).length > 3 && (
              <span
                className="px-1.5 py-0.5 rounded text-[8px] font-black border border-gray-200 text-gray-500"
                style={{ background: colors2000s.bg.disabled }}
              >
                +{(staff.serviceIds || []).length - 3}
              </span>
            )}
          </div>
        </div>

        {/* Outlined Action Buttons in Footer */}
        <div
          className="grid grid-cols-2 gap-3 pt-4 border-t"
          style={{ borderColor: colors2000s.border.light }}
        >
          <button
            onClick={() => onEdit(staff)}
            className="flex items-center justify-center gap-2 py-2.5 px-3 rounded-xl font-black text-[10px] uppercase tracking-widest transition-all active:scale-95"
            style={buttonStyles2000s.default}
          >
            <Edit3 size={14} /> Editar
          </button>
          <button
            onClick={() => onDelete(staff.id)}
            className="flex items-center justify-center gap-2 py-2.5 px-3 rounded-xl font-black text-[10px] uppercase tracking-widest transition-all active:scale-95"
            style={{ ...buttonStyles2000s.default, color: '#ef4444' }}
          >
            <Trash2 size={14} /> Eliminar
          </button>
        </div>
      </div>
    </div>
  )
}
