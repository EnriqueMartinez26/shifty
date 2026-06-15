import React, { useMemo, useState } from 'react'

import { format, subDays } from 'date-fns'
import {
  Download,
  FileSpreadsheet,
  FileText,
  Loader2,
  Table2,
  TrendingUp,
  Users,
  Wallet
} from 'lucide-react'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import type { ReportExportFormat } from '../hooks/useReports'
import { useExportReport, useProfessionalReports, useReportSummary } from '../hooks/useReports'
import { currencyFmtEsAr as currencyFmt } from '../lib/formatters'
import {
  create2000sInputStyle,
  create2000sListCardStyle,
  create2000sPanelStyle
} from '../lib/surfaceStyles'

const toInputDate = (date: Date) => format(date, 'yyyy-MM-dd')
const ReportsPage: React.FC = () => {
  const [fromDate, setFromDate] = useState(toInputDate(subDays(new Date(), 7)))
  const [toDate, setToDate] = useState(toInputDate(new Date()))

  const summaryQuery = useReportSummary(fromDate, toDate)
  const professionalsQuery = useProfessionalReports(fromDate, toDate)
  const exportMutation = useExportReport()

  const summary = summaryQuery.data
  const stats = useMemo(() => summary?.stats, [summary])
  const clientStats = summary?.client_stats
  const debtSummary = summary?.debt_summary

  const downloadFile = async (formatName: ReportExportFormat) => {
    const result = await exportMutation.mutateAsync({ format: formatName, fromDate, toDate })
    const url = window.URL.createObjectURL(result.blob)
    const link = document.createElement('a')
    link.href = url
    link.download = result.filename
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  }

  const inputStyle = create2000sInputStyle()
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

  if (summaryQuery.isError) {
    return (
      <div className="space-y-8 animate-in fade-in duration-500">
        <div
          className="flex flex-wrap gap-4 items-end justify-between p-6 rounded-3xl"
          style={cardStyle}
        >
          <div>
            <h2
              className="text-2xl font-black uppercase tracking-tight"
              style={{ color: colors2000s.text.primary }}
            >
              Reportes
            </h2>
            <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
              Analiza turnos e ingresos y exporta resultados.
            </p>
          </div>
        </div>
        <div
          className="text-sm p-4 rounded-xl font-bold"
          style={{
            background: '#ffeeee',
            border: '1px solid #ffcccc',
            color: '#cc0000',
            boxShadow: colors2000s.shadows.insetDark
          }}
        >
          No se pudo cargar el reporte para el rango seleccionado.
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div
        className="flex flex-wrap gap-4 items-end justify-between p-6 rounded-3xl"
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
              className="block text-[10px] font-black uppercase tracking-widest mb-1"
              style={{ color: colors2000s.text.secondary }}
            >
              Desde
            </label>
            <input
              type="date"
              value={fromDate}
              onChange={(e) => setFromDate(e.target.value)}
              className="rounded-xl px-3 py-2 text-xs font-black outline-none"
              style={inputStyle}
            />
          </div>
          <div>
            <label
              className="block text-[10px] font-black uppercase tracking-widest mb-1"
              style={{ color: colors2000s.text.secondary }}
            >
              Hasta
            </label>
            <input
              type="date"
              value={toDate}
              onChange={(e) => setToDate(e.target.value)}
              className="rounded-xl px-3 py-2 text-xs font-black outline-none"
              style={inputStyle}
            />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6">
        <div className="p-5 rounded-2xl" style={cardStyle}>
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
        <div className="p-5 rounded-2xl" style={cardStyle}>
          <p
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            Ingresos
          </p>
          <p className="text-2xl font-black mt-1" style={{ color: colors2000s.orange.accent }}>
            {currencyFmt.format(stats?.total_revenue ?? 0)}
          </p>
        </div>
        <div className="p-5 rounded-2xl" style={cardStyle}>
          <p
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            Ticket promedio
          </p>
          <p className="text-2xl font-black mt-1" style={{ color: colors2000s.text.primary }}>
            {currencyFmt.format(stats?.average_ticket ?? 0)}
          </p>
        </div>
        <div className="p-5 rounded-2xl" style={cardStyle}>
          <p
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            Saldo en deuda
          </p>
          <p className="text-2xl font-black mt-1" style={{ color: colors2000s.text.primary }}>
            {currencyFmt.format(debtSummary?.outstanding_balance ?? 0)}
          </p>
        </div>
        <div className="p-5 rounded-2xl" style={cardStyle}>
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
        <div className="p-5 rounded-2xl" style={cardStyle}>
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
        <div className="p-5 rounded-2xl" style={cardStyle}>
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
        <div className="p-5 rounded-2xl" style={cardStyle}>
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

      <div className="flex flex-wrap gap-3">
        <button
          onClick={() => {
            void downloadFile('csv')
          }}
          disabled={exportMutation.isPending}
          className="px-5 py-3 rounded-xl text-xs font-black uppercase tracking-widest transition-all active:scale-95 disabled:opacity-50"
          style={buttonStyles2000s.default}
        >
          <Table2 className="w-4 h-4 mr-2" /> Exportar CSV
        </button>
        <button
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

      <div className="grid xl:grid-cols-3 gap-6">
        <div className="rounded-3xl overflow-hidden" style={create2000sListCardStyle()}>
          <div
            className="px-6 py-4 font-black uppercase tracking-tight text-sm"
            style={{
              background: colors2000s.bg.disabled,
              borderBottom: `1px solid ${colors2000s.border.default}`,
              color: colors2000s.text.primary
            }}
          >
            Servicios mas vendidos
          </div>
          <div className="p-4 space-y-3">
            {(summary?.top_services || []).map((item) => (
              <div
                key={item.service_id}
                className="rounded-2xl p-4"
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
                  {currencyFmt.format(item.revenue)}
                </p>
              </div>
            ))}
            {(summary?.top_services.length ?? 0) === 0 && (
              <div
                className="rounded-2xl p-4 text-sm font-bold"
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

        <div className="rounded-3xl overflow-hidden" style={create2000sListCardStyle()}>
          <div
            className="px-6 py-4 font-black uppercase tracking-tight text-sm"
            style={{
              background: colors2000s.bg.disabled,
              borderBottom: `1px solid ${colors2000s.border.default}`,
              color: colors2000s.text.primary
            }}
          >
            Clientes frecuentes
          </div>
          <div className="p-4 space-y-3">
            {(summary?.top_clients || []).map((item) => (
              <div
                key={item.client_id}
                className="rounded-2xl p-4"
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
                  {currencyFmt.format(item.revenue)}
                </p>
              </div>
            ))}
            {(summary?.top_clients.length ?? 0) === 0 && (
              <div
                className="rounded-2xl p-4 text-sm font-bold"
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

        <div className="rounded-3xl overflow-hidden" style={create2000sListCardStyle()}>
          <div
            className="px-6 py-4 font-black uppercase tracking-tight text-sm"
            style={{
              background: colors2000s.bg.disabled,
              borderBottom: `1px solid ${colors2000s.border.default}`,
              color: colors2000s.text.primary
            }}
          >
            Top deudores
          </div>
          <div className="p-4 space-y-3">
            {(debtSummary?.top_debtors || []).map((item) => (
              <div
                key={item.client_id}
                className="rounded-2xl p-4"
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
                  {currencyFmt.format(item.balance)}
                </p>
              </div>
            ))}
            {(debtSummary?.top_debtors.length ?? 0) === 0 && (
              <div
                className="rounded-2xl p-4 text-sm font-bold"
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

      <div className="rounded-3xl overflow-hidden shadow-xl" style={create2000sListCardStyle()}>
        <div
          className="px-6 py-4 flex items-center gap-2 font-black uppercase tracking-tight text-sm"
          style={{
            background: colors2000s.bg.disabled,
            borderBottom: `1px solid ${colors2000s.border.default}`,
            color: colors2000s.text.primary
          }}
        >
          <Download className="w-4 h-4" /> Detalle de turnos
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
                <th className="text-left px-6 py-4 font-black uppercase tracking-widest">Fecha</th>
                <th className="text-left px-6 py-4 font-black uppercase tracking-widest">Estado</th>
                <th className="text-left px-6 py-4 font-black uppercase tracking-widest">
                  Servicio
                </th>
                <th className="text-left px-6 py-4 font-black uppercase tracking-widest">Staff</th>
                <th className="text-left px-6 py-4 font-black uppercase tracking-widest">
                  Cliente
                </th>
                <th className="text-right px-6 py-4 font-black uppercase tracking-widest">
                  Precio
                </th>
              </tr>
            </thead>
            <tbody className="divide-y" style={{ borderColor: colors2000s.border.light }}>
              {summary?.appointments.map((item) => (
                <tr key={item.public_id} className="hover:bg-zinc-50 transition-colors">
                  <td className="px-6 py-4 font-bold" style={{ color: colors2000s.text.primary }}>
                    {format(new Date(item.starts_at), 'dd/MM/yyyy HH:mm')}
                  </td>
                  <td className="px-6 py-4">
                    <span
                      className="px-2 py-1 rounded font-black text-[10px] uppercase"
                      style={{
                        background: colors2000s.bg.disabled,
                        color: colors2000s.text.secondary
                      }}
                    >
                      {item.status}
                    </span>
                  </td>
                  <td className="px-6 py-4 font-black" style={{ color: colors2000s.orange.accent }}>
                    {item.service_name}
                  </td>
                  <td className="px-6 py-4 font-bold" style={{ color: colors2000s.text.primary }}>
                    {item.staff_name}
                  </td>
                  <td
                    className="px-6 py-4 font-medium"
                    style={{ color: colors2000s.text.secondary }}
                  >
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
              {(summary?.appointments.length ?? 0) === 0 && (
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
      </div>

      <div className="rounded-3xl overflow-hidden shadow-xl" style={create2000sListCardStyle()}>
        <div
          className="px-6 py-4 flex items-center gap-2 font-black uppercase tracking-tight text-sm"
          style={{
            background: colors2000s.bg.disabled,
            borderBottom: `1px solid ${colors2000s.border.default}`,
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
                  Ocupacion
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
                    {currencyFmt.format(item.revenue)}
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
