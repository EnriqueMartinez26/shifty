import React from 'react'

import { Loader2 } from 'lucide-react'

import type { RecentPortalBooking } from '@application/services/PortalBookingsService'

import { formatArgentinaDateDisplay, formatArgentinaTime } from '@shared/utils/argentinaTime'

import { colors2000s } from '../../../theme/colors'
import { bookingStatusLabel } from '../../lib/bookingStatusLabel'
import { formatRelative } from '../../lib/relativeTime'
import { create2000sEmptyStateStyle, create2000sListCardStyle } from '../../lib/surfaceStyles'
import { QueryErrorNotice } from '../molecules/QueryErrorNotice'

interface PortalBookingsListProps {
  bookings: RecentPortalBooking[]
  isLoading: boolean
  error: unknown
  selectedIds: ReadonlySet<string>
  onToggle: (id: string) => void
  onToggleAll: () => void
}

// Una sola estructura para telefono y escritorio: en el telefono cada fila es
// una tarjeta apilada; desde `md:` las celdas se alinean como una tabla con
// el encabezado de columnas.
const COLUMNS = 'md:grid md:grid-cols-[1.3fr_1fr_1.2fr_1.2fr_0.8fr] md:items-center md:gap-4'

const CHECKBOX_LABEL =
  'min-h-11 min-w-11 flex-shrink-0 inline-flex items-center justify-center cursor-pointer'

const startLabel = (iso: string): string =>
  `${formatArgentinaDateDisplay(iso)} · ${formatArgentinaTime(iso)} hs`

const Row: React.FC<{
  booking: RecentPortalBooking
  checked: boolean
  onToggle: (id: string) => void
}> = ({ booking, checked, onToggle }) => (
  <li
    className="flex items-start gap-2 p-3 rounded-2xl"
    style={create2000sListCardStyle(
      checked ? colors2000s.status.warning.bg : undefined,
      checked ? colors2000s.status.warning.border : undefined
    )}
  >
    <label className={CHECKBOX_LABEL}>
      <input
        type="checkbox"
        className="h-5 w-5 accent-orange-600"
        checked={checked}
        onChange={() => onToggle(booking.public_id)}
        aria-label={`Seleccionar a ${booking.client_name}, ${startLabel(booking.starts_at)}`}
      />
    </label>
    <div className={`min-w-0 flex-1 grid gap-1 py-2 text-sm ${COLUMNS}`}>
      <div className="min-w-0">
        <p className="font-black truncate" style={{ color: colors2000s.text.primary }}>
          {booking.client_name}
        </p>
        <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
          {booking.client_phone || 'Sin teléfono'}
        </p>
      </div>
      <p className="font-bold" style={{ color: colors2000s.text.primary }}>
        {startLabel(booking.starts_at)}
      </p>
      <div className="min-w-0 text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
        <span>{booking.service_name}</span>
        <span aria-hidden="true"> · </span>
        <span>{booking.staff_name}</span>
      </div>
      <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
        <span className="md:hidden">Reservó </span>
        <span>{formatRelative(booking.created_at)}</span>
      </p>
      <p className="text-xs font-black uppercase" style={{ color: colors2000s.text.secondary }}>
        {bookingStatusLabel(booking.status)}
      </p>
    </div>
  </li>
)

/**
 * Lista de reservas recientes del portal con casilleros para elegir cuales
 * cancelar. Presentacional: la seleccion y los datos vienen del contenedor.
 */
export const PortalBookingsList: React.FC<PortalBookingsListProps> = ({
  bookings,
  isLoading,
  error,
  selectedIds,
  onToggle,
  onToggleAll
}) => {
  if (isLoading) {
    return (
      <div
        role="status"
        className="flex items-center gap-2 p-6 text-xs font-black uppercase tracking-widest"
        style={{ color: colors2000s.text.secondary }}
      >
        <Loader2 className="w-4 h-4 animate-spin" />
        Cargando reservas…
      </div>
    )
  }

  if (error) {
    return (
      <QueryErrorNotice error={error} message="No se pudieron cargar las reservas del portal." />
    )
  }

  if (bookings.length === 0) {
    return (
      <p
        className="p-6 rounded-2xl text-sm font-bold text-center"
        style={{ ...create2000sEmptyStateStyle(), color: colors2000s.text.secondary }}
      >
        No hubo reservas desde el portal en este período.
      </p>
    )
  }

  const allSelected = bookings.every((booking) => selectedIds.has(booking.public_id))

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 px-3">
        <label className={`${CHECKBOX_LABEL} md:min-w-0 gap-2 md:justify-start`}>
          <input
            type="checkbox"
            className="h-5 w-5 accent-orange-600"
            checked={allSelected}
            onChange={onToggleAll}
            aria-label="Seleccionar todas"
          />
          <span
            className="text-xs font-black uppercase tracking-widest md:sr-only"
            style={{ color: colors2000s.text.secondary }}
            aria-hidden="true"
          >
            Seleccionar todas
          </span>
        </label>
        <div
          aria-hidden="true"
          className={`hidden flex-1 text-[10px] font-black uppercase tracking-widest ${COLUMNS}`}
          style={{ color: colors2000s.text.secondary }}
        >
          <span>Cliente</span>
          <span>Turno</span>
          <span>Servicio · Profesional</span>
          <span>Reservó</span>
          <span>Estado</span>
        </div>
      </div>
      <ul className="space-y-2">
        {bookings.map((booking) => (
          <Row
            key={booking.public_id}
            booking={booking}
            checked={selectedIds.has(booking.public_id)}
            onToggle={onToggle}
          />
        ))}
      </ul>
    </div>
  )
}
