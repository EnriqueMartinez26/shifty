import React, { useState } from 'react'

import { subDays } from 'date-fns'
import { FileSpreadsheet, FileText, Loader2, Table2, TrendingUp, Users, Wallet } from 'lucide-react'

import type { ReportSummary } from '@application/services/ReportsService'

import { getErrorMessage } from '@shared/errors/getErrorMessage'
import { formatArgentinaDate } from '@shared/utils/argentinaTime'
import { formatCurrency } from '@shared/utils/currency'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { ReportAppointmentsTable } from '../components/organisms/ReportAppointmentsTable'
import { useAuth } from '../context/AuthContext'
import { hasAnyRole, ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN } from '../context/roles'
import type { ReportExportFormat } from '../hooks/useReports'
import { useExportReport, useProfessionalReports, useReportSummary } from '../hooks/useReports'
import {
  create2000sInputStyle,
  create2000sListCardStyle,
  create2000sPanelStyle
} from '../lib/surfaceStyles'

/** El rango del reporte es un dia de negocio argentino, no el del navegador. */
const toInputDate = (date: Date) => formatArgentinaDate(date.toISOString())

/** Turnos por pagina del detalle (el backend acepta hasta 5000). */
const REPORT_PAGE_SIZE = 100

interface ReportRangeHeaderProps {
  fromDate: string
  toDate: string
  onFromChange: (value: string) => void
  onToChange: (value: string) => void
}

/**
 * Titulo y rango del reporte. Se muestra tambien cuando el rango falla: la
 * pantalla de error lo escondia y con un rango invalido (400, mas de 370 dias
 * o desde > hasta) no habia forma de corregirlo (FF-19).
 */
const ReportRangeHeader: React.FC<ReportRangeHeaderProps> = ({
  fromDate,
  toDate,
  onFromChange,
  onToChange
}) => (
  <div
    className="flex flex-wrap gap-4 items-end justify-between p-6 rounded-lg"
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
        Reportes
      </h2>
      <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
        Analiza turnos, clientes, servicios y deuda.
      </p>
    </div>

    <div className="flex flex-wrap gap-3 items-end">
      <div>
        <label
          htmlFor="reports-from-date"
          className="block text-[10px] font-black uppercase tracking-widest mb-1"
          style={{ color: colors2000s.text.secondary }}
        >
          Desde
        </label>
        <input
          id="reports-from-date"
          type="date"
          value={fromDate}
          onChange={(e) => onFromChange(e.target.value)}
          className="rounded-xl px-3 py-2 text-xs font-black outline-none"
          style={create2000sInputStyle()}
        />
      </div>
      <div>
        <label
          htmlFor="reports-to-date"
          className="block text-[10px] font-black uppercase tracking-widest mb-1"
          style={{ color: colors2000s.text.secondary }}
        >
          Hasta
        </label>
        <input
          id="reports-to-date"
          type="date"
          value={toDate}
          onChange={(e) => onToChange(e.target.value)}
          className="rounded-xl px-3 py-2 text-xs font-black outline-none"
          style={create2000sInputStyle()}
        />
      </div>
    </div>
  </div>
)

const ReportsPage: React.FC = () => {
  const [fromDate, setFromDate] = useState(toInputDate(subDays(new Date(), 7)))
  const [toDate, setToDate] = useState(toInputDate(new Date()))
  const [offset, setOffset] = useState(0)
  const { user } = useAuth()
  // El backend exporta solo para admins (REPORT_EXPORTERS): el profesional
  // veia los botones y recibia un 403 (FF-18).
  const canExport = hasAnyRole(
    user?.role,
    [ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN],
    user?.is_global_admin
  )

  const summaryQuery = useReportSummary(fromDate, toDate, true, {
    limit: REPORT_PAGE_SIZE,
    offset
  })
  const professionalsQuery = useProfessionalReports(fromDate, toDate)
  const exportMutation = useExportReport()
  const [exportError, setExportError] = useState<string | null>(null)

  // Ultimo resumen bueno del rango: si falla una pagina posterior, la
  // pantalla queda y el error va junto a la paginacion. Estado ajustado en
  // el render (sin efecto, regla 27).
  const rangeKey = `${fromDate}|${toDate}`
  const [lastGood, setLastGood] = useState<{
    key: string
    offset: number
    data: ReportSummary
  } | null>(null)
  if (
    summaryQuery.data &&
    summaryQuery.data !== lastGood?.data &&
    !summaryQuery.isPlaceholderData
  ) {
    setLastGood({ key: rangeKey, offset, data: summaryQuery.data })
  }
  const fallback = !summaryQuery.data && lastGood?.key === rangeKey ? lastGood : null
  const summary = summaryQuery.data ?? fallback?.data
  // Filas y rotulo salen de la misma pagina: la ultima buena si la pedida
  // fallo o todavia no llego (placeholder).
  const shown = summaryQuery.isPlaceholderData && lastGood?.key === rangeKey ? lastGood : fallback
  const shownOffset = shown?.offset ?? offset
  const stats = summary?.stats
  const clientStats = summary?.client_stats
  const debtSummary = summary?.debt_summary

  /**
   * Sin este `catch`, un export rechazado quedaba en nada: la promesa se
   * descartaba con `void`, `isPending` volvia a false y el boton no decia
   * nada. Un rango mayor a REPORT_MAX_RANGE_DAYS devuelve 400 con el motivo
   * exacto; el usuario no lo veia y volvia a apretar.
   */
  const downloadFile = async (formatName: ReportExportFormat) => {
    setExportError(null)
    try {
      const result = await exportMutation.mutateAsync({ format: formatName, fromDate, toDate })
      const url = window.URL.createObjectURL(result.blob)
      const link = document.createElement('a')
      link.href = url
      link.download = result.filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (error: unknown) {
      setExportError(getErrorMessage(error, 'No se pudo exportar el reporte'))
    }
  }

  const cardStyle = create2000sPanelStyle()

  if (summaryQuery.isLoading) {
    return (
      <div
        className="h-60 flex items-center justify-center gap-3"
        style={{ color: colors2000s.text.secondary }}
      >
        <Loader2 className="w-5 h-5 animate-spin" style={{ color: colors2000s.orange.accent }} />
        <span className="text-xs font-black uppercase tracking-widest">Generando reporte...</span>
      </div>
    )
  }

  const rangeHeader = (
    <ReportRangeHeader
      fromDate={fromDate}
      toDate={toDate}
      onFromChange={(value) => {
        setFromDate(value)
        setOffset(0)
      }}
      onToChange={(value) => {
        setToDate(value)
        setOffset(0)
      }}
    />
  )

  if (summaryQuery.isError && !summary) {
    return (
      <div className="space-y-8 duration-500">
        {rangeHeader}
        <div
          role="alert"
          className="text-sm p-4 rounded-lg font-bold"
          style={{
            background: colors2000s.status.danger.bg,
            border: `1px solid ${colors2000s.status.danger.border}`,
            color: colors2000s.status.danger.text,
            boxShadow: colors2000s.shadows.insetDark
          }}
        >
          No se pudo cargar el reporte para el rango seleccionado. Revisá que &quot;Desde&quot; sea
          anterior a &quot;Hasta&quot; o probá con un rango más corto.
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-8 duration-500">
      {rangeHeader}

      <div className="grid grid-cols-2 xl:grid-cols-4 gap-6">
        <div className="p-5 rounded-md" style={cardStyle}>
          <p
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            Total turnos
          </p>
          <p className="text-2xl font-black mt-1" style={{ color: colors2000s.text.primary }}>
            {stats?.total_appointments ?? 0}
          </p>
        </div>
        <div className="p-5 rounded-md" style={cardStyle}>
          <p
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            Ingresos
          </p>
          <p className="text-2xl font-black mt-1" style={{ color: colors2000s.orange.accent }}>
            {formatCurrency(stats?.total_revenue ?? 0)}
          </p>
        </div>
        <div className="p-5 rounded-md" style={cardStyle}>
          <p
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            Ticket promedio
          </p>
          <p className="text-2xl font-black mt-1" style={{ color: colors2000s.text.primary }}>
            {formatCurrency(stats?.average_ticket ?? 0)}
          </p>
        </div>
        <div className="p-5 rounded-md" style={cardStyle}>
          <p
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            Saldo en deuda
          </p>
          <p className="text-2xl font-black mt-1" style={{ color: colors2000s.text.primary }}>
            {formatCurrency(debtSummary?.outstanding_balance ?? 0)}
          </p>
        </div>
        <div className="p-5 rounded-md" style={cardStyle}>
          <p
            className="text-[10px] font-black uppercase tracking-widest flex items-center gap-2"
            style={{ color: colors2000s.text.secondary }}
          >
            <Users className="w-3.5 h-3.5" /> Clientes en rango
          </p>
          <p className="text-2xl font-black mt-1" style={{ color: colors2000s.text.primary }}>
            {clientStats?.total_clients ?? 0}
          </p>
        </div>
        <div className="p-5 rounded-md" style={cardStyle}>
          <p
            className="text-[10px] font-black uppercase tracking-widest flex items-center gap-2"
            style={{ color: colors2000s.text.secondary }}
          >
            <TrendingUp className="w-3.5 h-3.5" /> Nuevos clientes
          </p>
          <p className="text-2xl font-black mt-1" style={{ color: colors2000s.text.primary }}>
            {clientStats?.new_clients ?? 0}
          </p>
        </div>
        <div className="p-5 rounded-md" style={cardStyle}>
          <p
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            Recurrentes
          </p>
          <p className="text-2xl font-black mt-1" style={{ color: colors2000s.text.primary }}>
            {clientStats?.returning_clients ?? 0}
          </p>
        </div>
        <div className="p-5 rounded-md" style={cardStyle}>
          <p
            className="text-[10px] font-black uppercase tracking-widest flex items-center gap-2"
            style={{ color: colors2000s.text.secondary }}
          >
            <Wallet className="w-3.5 h-3.5" /> Clientes con deuda
          </p>
          <p className="text-2xl font-black mt-1" style={{ color: colors2000s.text.primary }}>
            {debtSummary?.debtors_count ?? 0}
          </p>
        </div>
      </div>

      {canExport && (
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={() => {
              void downloadFile('csv')
            }}
            disabled={exportMutation.isPending}
            className="px-5 py-3 text-xs font-black uppercase tracking-widest transition-all active:scale-95 disabled:opacity-50"
            style={buttonStyles2000s.default}
          >
            <Table2 className="w-4 h-4 mr-2" /> Exportar CSV
          </button>
          <button
            type="button"
            onClick={() => {
              void downloadFile('excel')
            }}
            disabled={exportMutation.isPending}
            className="px-5 py-3 rounded-xl text-xs font-black uppercase tracking-widest transition-all active:scale-95 disabled:opacity-50"
            style={{
              ...buttonStyles2000s.selected,
              background: 'linear-gradient(180deg, #10b981 0%, #059669 100%)',
              border: '1px solid #059669'
            }}
          >
            <FileSpreadsheet className="w-4 h-4 mr-2" /> Exportar Excel
          </button>
          <button
            type="button"
            onClick={() => {
              void downloadFile('pdf')
            }}
            disabled={exportMutation.isPending}
            className="px-5 py-3 rounded-xl text-xs font-black uppercase tracking-widest transition-all active:scale-95 disabled:opacity-50"
            style={{
              ...buttonStyles2000s.selected,
              background: 'linear-gradient(180deg, #3b82f6 0%, #2563eb 100%)',
              border: '1px solid #2563eb'
            }}
          >
            <FileText className="w-4 h-4 mr-2" /> Exportar PDF
          </button>
        </div>
      )}

      {exportError && (
        <div
          role="alert"
          className="text-sm p-4 rounded-lg font-bold"
          style={{
            background: colors2000s.status.danger.bg,
            border: `1px solid ${colors2000s.status.danger.border}`,
            color: colors2000s.status.danger.text,
            boxShadow: colors2000s.shadows.insetDark
          }}
        >
          {exportError}
        </div>
      )}

      <div className="grid xl:grid-cols-3 gap-6">
        <div className="rounded-lg overflow-hidden" style={create2000sListCardStyle()}>
          <div
            className="px-6 py-4 font-black uppercase tracking-tight text-sm"
            style={{
              background: colors2000s.bg.disabled,
              color: colors2000s.text.primary
            }}
          >
            Servicios más vendidos
          </div>
          <div className="p-4 space-y-3">
            {(summary?.top_services || []).map((item) => (
              <div
                key={item.service_id}
                className="rounded-md p-4"
                style={{
                  background: colors2000s.bg.disabledBottom,
                  border: `1px solid ${colors2000s.border.light}`
                }}
              >
                <p className="text-sm font-black" style={{ color: colors2000s.text.primary }}>
                  {item.service_name}
                </p>
                <p
                  className="text-[11px] font-bold mt-1"
                  style={{ color: colors2000s.text.secondary }}
                >
                  {item.appointments} reservas · {item.completed_appointments} completados
                </p>
                <p className="text-xs font-black mt-2" style={{ color: colors2000s.orange.accent }}>
                  {formatCurrency(item.revenue)}
                </p>
              </div>
            ))}
            {(summary?.top_services.length ?? 0) === 0 && (
              <div
                className="rounded-md p-4 text-sm font-bold"
                style={{
                  background: colors2000s.bg.disabledBottom,
                  color: colors2000s.text.secondary
                }}
              >
                Sin servicios destacados para este rango.
              </div>
            )}
          </div>
        </div>

        <div className="rounded-lg overflow-hidden" style={create2000sListCardStyle()}>
          <div
            className="px-6 py-4 font-black uppercase tracking-tight text-sm"
            style={{
              background: colors2000s.bg.disabled,
              color: colors2000s.text.primary
            }}
          >
            Clientes frecuentes
          </div>
          <div className="p-4 space-y-3">
            {(summary?.top_clients || []).map((item) => (
              <div
                key={item.client_id}
                className="rounded-md p-4"
                style={{
                  background: colors2000s.bg.disabledBottom,
                  border: `1px solid ${colors2000s.border.light}`
                }}
              >
                <p className="text-sm font-black" style={{ color: colors2000s.text.primary }}>
                  {item.client_name}
                </p>
                <p
                  className="text-[11px] font-bold mt-1"
                  style={{ color: colors2000s.text.secondary }}
                >
                  {item.appointments} reservas · {item.completed_appointments} completados
                </p>
                <p className="text-xs font-black mt-2" style={{ color: colors2000s.orange.accent }}>
                  {formatCurrency(item.revenue)}
                </p>
              </div>
            ))}
            {(summary?.top_clients.length ?? 0) === 0 && (
              <div
                className="rounded-md p-4 text-sm font-bold"
                style={{
                  background: colors2000s.bg.disabledBottom,
                  color: colors2000s.text.secondary
                }}
              >
                Sin clientes frecuentes para este rango.
              </div>
            )}
          </div>
        </div>

        <div className="rounded-lg overflow-hidden" style={create2000sListCardStyle()}>
          <div
            className="px-6 py-4 font-black uppercase tracking-tight text-sm"
            style={{
              background: colors2000s.bg.disabled,
              color: colors2000s.text.primary
            }}
          >
            Top deudores
          </div>
          <div className="p-4 space-y-3">
            {(debtSummary?.top_debtors || []).map((item) => (
              <div
                key={item.client_id}
                className="rounded-md p-4"
                style={{
                  background: colors2000s.bg.disabledBottom,
                  border: `1px solid ${colors2000s.border.light}`
                }}
              >
                <p className="text-sm font-black" style={{ color: colors2000s.text.primary }}>
                  {item.client_name}
                </p>
                <p
                  className="text-[11px] font-bold mt-1"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Cliente con saldo pendiente
                </p>
                <p className="text-xs font-black mt-2" style={{ color: colors2000s.orange.accent }}>
                  {formatCurrency(item.balance)}
                </p>
              </div>
            ))}
            {(debtSummary?.top_debtors.length ?? 0) === 0 && (
              <div
                className="rounded-md p-4 text-sm font-bold"
                style={{
                  background: colors2000s.bg.disabledBottom,
                  color: colors2000s.text.secondary
                }}
              >
                No hay deuda pendiente registrada.
              </div>
            )}
          </div>
        </div>
      </div>

      <ReportAppointmentsTable
        appointments={summary?.appointments ?? []}
        total={stats?.total_appointments ?? 0}
        offset={shownOffset}
        pageSize={REPORT_PAGE_SIZE}
        hasMore={summary?.has_more ?? false}
        isStale={summaryQuery.isPlaceholderData}
        pageFailed={summaryQuery.isError}
        onRetry={() => void summaryQuery.refetch()}
        onOffsetChange={setOffset}
      />

      <div className="rounded-lg overflow-hidden shadow-xl" style={create2000sListCardStyle()}>
        <div
          className="px-6 py-4 flex items-center gap-2 font-black uppercase tracking-tight text-sm"
          style={{
            background: colors2000s.bg.disabled,
            color: colors2000s.text.primary
          }}
        >
          <Table2 className="w-4 h-4" /> Rendimiento por profesional
        </div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-xs">
            <thead
              style={{
                background: colors2000s.bg.disabledBottom,
                color: colors2000s.text.secondary
              }}
            >
              <tr>
                <th className="text-left px-6 py-4 font-black uppercase tracking-widest">
                  Profesional
                </th>
                <th className="text-right px-6 py-4 font-black uppercase tracking-widest">
                  Horas usadas
                </th>
                <th className="text-right px-6 py-4 font-black uppercase tracking-widest">
                  Horas disponibles
                </th>
                <th className="text-right px-6 py-4 font-black uppercase tracking-widest">
                  Horas bloqueadas
                </th>
                <th className="text-right px-6 py-4 font-black uppercase tracking-widest">
                  Ocupación
                </th>
                <th className="text-right px-6 py-4 font-black uppercase tracking-widest">
                  Ingresos
                </th>
              </tr>
            </thead>
            <tbody className="divide-y" style={{ borderColor: colors2000s.border.light }}>
              {(professionalsQuery.data?.professionals ?? []).map((item) => (
                <tr key={item.staff_id} className="hover:bg-zinc-50 transition-colors">
                  <td className="px-6 py-4 font-black" style={{ color: colors2000s.text.primary }}>
                    {item.staff_name}
                  </td>
                  <td
                    className="px-6 py-4 text-right font-semibold"
                    style={{ color: colors2000s.text.primary }}
                  >
                    {item.used_hours}
                  </td>
                  <td
                    className="px-6 py-4 text-right font-semibold"
                    style={{ color: colors2000s.text.primary }}
                  >
                    {item.available_hours}
                  </td>
                  <td
                    className="px-6 py-4 text-right font-semibold"
                    style={{ color: colors2000s.text.primary }}
                  >
                    {item.blocked_hours}
                  </td>
                  <td
                    className="px-6 py-4 text-right font-black"
                    style={{ color: colors2000s.orange.accent }}
                  >
                    {item.occupancy_rate}%
                  </td>
                  <td
                    className="px-6 py-4 text-right font-black"
                    style={{ color: colors2000s.text.primary }}
                  >
                    {formatCurrency(item.revenue)}
                  </td>
                </tr>
              ))}
              {!professionalsQuery.isLoading &&
                (professionalsQuery.data?.professionals.length ?? 0) === 0 && (
                  <tr>
                    <td
                      colSpan={6}
                      className="px-6 py-10 text-center font-bold italic"
                      style={{ color: colors2000s.text.disabled }}
                    >
                      Sin datos de profesionales para el rango.
                    </td>
                  </tr>
                )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

export default ReportsPage
