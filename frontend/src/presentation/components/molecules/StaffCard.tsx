import React from 'react'

import { Mail, Edit3, Trash2, Check, X, LayoutGrid } from 'lucide-react'

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

  // Un recurso (cancha, sala, box) no tiene nombre ni apellido: las
  // iniciales salen del nombre de muestra.
  const initials = staff.isResource
    ? getInitials(staff.displayName ?? '', '')
    : getInitials(staff.firstName, staff.lastName)
  const isResource = staff.isResource

  // Azul para recursos (canchas, salas), naranja para personas.
  const accentBorderColor = isResource ? colors2000s.status.info.dark : colors2000s.orange.light
  const avatarGradient = isResource
    ? `linear-gradient(180deg, ${colors2000s.status.info.light} 0%, ${colors2000s.status.info.dark} 100%)`
    : `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`

  return (
    <div
      className="relative p-6 rounded-md transition-all duration-200 hover:scale-[1.01] active:scale-[0.99] border-l-[6px]"
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
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-[9px] font-black uppercase tracking-widest"
          style={{
            background: 'white',
            boxShadow: colors2000s.shadows.insetDark,
            color: staff.isActive ? colors2000s.status.success.text : colors2000s.text.disabled
          }}
        >
          {staff.isActive ? (
            <Check size={12} color={colors2000s.status.success.dark} />
          ) : (
            <X size={12} color={colors2000s.text.disabled} />
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
              boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
            }}
          >
            {initials}
          </div>
          <div className="min-w-0">
            <h3
              className="font-black text-sm uppercase tracking-tight truncate leading-tight"
              style={{ color: colors2000s.text.primary }}
            >
              {staff.displayName}
            </h3>
            <p
              className="text-[10px] font-black uppercase tracking-widest mt-1 truncate"
              style={{ color: colors2000s.text.disabled }}
            >
              {isResource ? 'Recurso' : staff.fullName}
            </p>
          </div>
        </div>

        {/* Email contact field (a resource has no email nor login) */}
        <div
          className="flex items-center gap-2 text-xs font-bold pt-1"
          style={{ color: colors2000s.text.secondary }}
        >
          {staff.email ? (
            <>
              <Mail size={14} color={colors2000s.text.disabled} />
              <span className="truncate">{staff.email.getValue()}</span>
            </>
          ) : (
            <>
              <LayoutGrid size={14} color={colors2000s.text.disabled} />
              <span className="truncate">Cancha, sala o box: sin usuario</span>
            </>
          )}
        </div>

        {/* Metadata Specialties Section */}
        <div className="flex items-center gap-2 pt-3">
          <span
            className="text-[9px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.disabled }}
          >
            Servicios:
          </span>
          <div className="flex flex-wrap gap-1">
            {(staff.serviceIds || []).length === 0 ? (
              <span
                className="text-[9px] font-bold italic"
                style={{ color: colors2000s.text.disabled }}
              >
                Sin servicios
              </span>
            ) : (
              (staff.serviceIds || []).slice(0, 3).map((id, index) => (
                <span
                  key={id}
                  className="px-2 py-0.5 rounded-md text-[8px] font-black uppercase tracking-widest"
                  style={{
                    background: 'white',
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
                className="px-1.5 py-0.5 rounded-md text-[8px] font-black"
                style={{
                  background: colors2000s.bg.disabled,
                  color: colors2000s.text.secondary
                }}
              >
                +{(staff.serviceIds || []).length - 3}
              </span>
            )}
          </div>
        </div>

        {/* Outlined Action Buttons in Footer */}
        <div className="grid grid-cols-2 gap-3 pt-4">
          <button
            onClick={() => onEdit(staff)}
            className="flex items-center justify-center gap-2 py-2.5 px-3 font-black text-[10px] uppercase tracking-widest transition-all active:scale-95"
            style={buttonStyles2000s.default}
          >
            <Edit3 size={14} /> Editar
          </button>
          <button
            onClick={() => onDelete(staff.id)}
            className="flex items-center justify-center gap-2 py-2.5 px-3 font-black text-[10px] uppercase tracking-widest transition-all active:scale-95"
            style={{ ...buttonStyles2000s.default, color: colors2000s.status.danger.light }}
          >
            <Trash2 size={14} /> Eliminar
          </button>
        </div>
      </div>
    </div>
  )
}
