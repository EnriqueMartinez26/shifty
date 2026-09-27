import React from 'react'

import { Download } from 'lucide-react'

import type { ReportAppointmentItem } from '@application/services/ReportsService'

import { formatArgentinaDateDisplay, formatArgentinaTime } from '@shared/utils/argentinaTime'

import { buttonStyles2000s, colors2000s } from '../../../theme/colors'
import { bookingStatusLabel } from '../../lib/bookingStatusLabel'
import { currencyFmtEsAr as currencyFmt } from '../../lib/formatters'
import { create2000sListCardStyle } from '../../lib/surfaceStyles'

interface ReportAppointmentsTableProps {
  appointments: ReportAppointmentItem[]
  /** Turnos del rango completo (`stats.total_appointments`), no de la pagina. */
  total: number
  offset: number
  pageSize: number
  hasMore: boolean
  /** La pagina que se ve es la anterior mientras llega la pedida. */
  isStale: boolean
  /** Fallo la pagina pedida; se sigue viendo la ultima buena. */
  pageFailed: boolean
  /** Vuelve a pedir la pagina que fallo. */
  onRetry: () => void
  onOffsetChange: (offset: number) => void
}

/** Detalle de turnos del reporte, de a una pagina (FF-30). */
export const ReportAppointmentsTable: React.FC<ReportAppointmentsTableProps> = ({
  appointments,
  total,
  offset,
  pageSize,
  hasMore,
  isStale,
  pageFailed,
  onRetry,
  onOffsetChange
}) => {
  const first = appointments.length > 0 ? offset + 1 : 0
  const last = offset + appointments.length

  return (
    <div className="rounded-lg overflow-hidden shadow-xl" style={create2000sListCardStyle()}>
      <div
        className="px-6 py-4 flex items-center gap-2 font-black uppercase tracking-tight text-sm"
        style={{
          background: colors2000s.bg.disabled,
          color: colors2000s.text.primary
        }}
      >
        <Download className="w-4 h-4" /> Detalle de turnos
      </div>
      <div className="overflow-x-auto" style={{ opacity: isStale ? 0.6 : 1 }} aria-busy={isStale}>
        <table className="min-w-full text-xs">
          <thead
            style={{
              background: colors2000s.bg.disabledBottom,
              color: colors2000s.text.secondary
            }}
          >
            <tr>
              <th className="text-left px-6 py-4 font-black uppercase tracking-widest">Fecha</th>
              <th className="text-left px-6 py-4 font-black uppercase tracking-widest">Estado</th>
              <th className="text-left px-6 py-4 font-black uppercase tracking-widest">Servicio</th>
              <th className="text-left px-6 py-4 font-black uppercase tracking-widest">Staff</th>
              <th className="text-left px-6 py-4 font-black uppercase tracking-widest">Cliente</th>
              <th className="text-right px-6 py-4 font-black uppercase tracking-widest">Precio</th>
            </tr>
          </thead>
          <tbody className="divide-y" style={{ borderColor: colors2000s.border.light }}>
            {appointments.map((item) => (
              <tr key={item.public_id} className="hover:bg-zinc-50 transition-colors">
                <td className="px-6 py-4 font-bold" style={{ color: colors2000s.text.primary }}>
                  {formatArgentinaDateDisplay(item.starts_at)} {formatArgentinaTime(item.starts_at)}
                </td>
                <td className="px-6 py-4">
                  <span
                    className="px-2 py-1 rounded font-black text-[10px] uppercase"
                    style={{
                      background: colors2000s.bg.disabled,
                      color: colors2000s.text.secondary
                    }}
                  >
                    {bookingStatusLabel(item.status)}
                  </span>
                </td>
                <td className="px-6 py-4 font-black" style={{ color: colors2000s.orange.accent }}>
                  {item.service_name}
                </td>
                <td className="px-6 py-4 font-bold" style={{ color: colors2000s.text.primary }}>
                  {item.staff_name}
                </td>
                <td className="px-6 py-4 font-medium" style={{ color: colors2000s.text.secondary }}>
                  {item.client_name}
                </td>
                <td
                  className="px-6 py-4 font-black text-right"
                  style={{ color: colors2000s.text.primary }}
                >
                  {currencyFmt.format(item.service_price)}
                </td>
              </tr>
            ))}
            {appointments.length === 0 && (
              <tr>
                <td
                  colSpan={6}
                  className="px-6 py-12 text-center font-bold italic"
                  style={{ color: colors2000s.text.disabled }}
                >
                  No hay turnos en el rango seleccionado.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div
        className="px-6 py-3 flex flex-wrap items-center justify-between gap-3 text-xs font-bold"
        style={{ color: colors2000s.text.secondary }}
      >
        <span>
          {first}–{last} de {total}
          {isStale ? ' · Actualizando...' : ''}
        </span>
        {pageFailed && (
          <span role="alert" style={{ color: colors2000s.status.danger.text }}>
            No se pudo cargar esta pagina del detalle.{' '}
            <button type="button" onClick={onRetry} className="underline">
              Reintentar
            </button>
          </span>
        )}
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => onOffsetChange(Math.max(0, offset - pageSize))}
            disabled={offset === 0 || isStale}
            className="px-4 py-2 text-xs font-black uppercase tracking-widest disabled:opacity-50"
            style={buttonStyles2000s.default}
          >
            Anterior
          </button>
          <button
            type="button"
            onClick={() => onOffsetChange(offset + pageSize)}
            disabled={!hasMore || isStale}
            className="px-4 py-2 text-xs font-black uppercase tracking-widest disabled:opacity-50"
            style={buttonStyles2000s.default}
          >
            Siguiente
          </button>
        </div>
      </div>
    </div>
  )
}
