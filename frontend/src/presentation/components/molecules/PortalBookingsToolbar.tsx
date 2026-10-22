import React from 'react'

import { XCircle } from 'lucide-react'

import type { PortalBookingsWindowHours } from '@application/services/PortalBookingsService'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'

const WINDOWS: { hours: PortalBookingsWindowHours; label: string }[] = [
  { hours: 24, label: 'Últimas 24 h' },
  { hours: 72, label: 'Últimas 72 h' },
  { hours: 168, label: 'Últimos 7 días' }
]

interface PortalBookingsToolbarProps {
  hours: PortalBookingsWindowHours
  onHoursChange: (hours: PortalBookingsWindowHours) => void
  selectedCount: number
  onCancelSelected: () => void
  /** Tienda suspendida: cancelar queda deshabilitado con este motivo. */
  readOnlyReason?: string
}

/** Ventana de tiempo de la lista y la accion sobre las reservas elegidas. */
export const PortalBookingsToolbar: React.FC<PortalBookingsToolbarProps> = ({
  hours,
  onHoursChange,
  selectedCount,
  onCancelSelected,
  readOnlyReason
}) => (
  <div className="flex flex-wrap items-center justify-between gap-3">
    <div role="group" aria-label="Período" className="flex flex-wrap gap-2">
      {WINDOWS.map((option) => {
        const isActive = option.hours === hours
        return (
          <button
            key={option.hours}
            type="button"
            aria-pressed={isActive}
            onClick={() => onHoursChange(option.hours)}
            className="min-h-11 px-4 rounded-xl text-xs font-black uppercase tracking-widest"
            style={isActive ? buttonStyles2000s.selected : buttonStyles2000s.default}
          >
            {option.label}
          </button>
        )
      })}
    </div>
    <div className="flex flex-col items-stretch gap-1 w-full sm:w-auto sm:items-end">
      <button
        type="button"
        onClick={onCancelSelected}
        disabled={selectedCount === 0 || Boolean(readOnlyReason)}
        title={readOnlyReason}
        className="min-h-11 px-4 rounded-xl inline-flex items-center justify-center gap-2 bg-white border text-xs font-black uppercase tracking-widest text-red-700 border-red-200 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        <XCircle className="w-4 h-4" />
        {`Cancelar seleccionadas (${selectedCount})`}
      </button>
      {readOnlyReason && (
        <p className="text-xs font-bold" style={{ color: colors2000s.status.warning.text }}>
          {readOnlyReason}
        </p>
      )}
    </div>
  </div>
)
