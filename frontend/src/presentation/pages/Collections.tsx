import React, { useMemo, useState } from 'react'
import { AlertCircle, CheckCircle2, CreditCard, ExternalLink, Link2, Loader2 } from 'lucide-react'

import {
  useCreatePaymentPreference,
  useManualConfirmPayment,
  usePaymentsAppointments,
  useReconciliationSummary
} from '../hooks/usePayments'
import { buttonStyles2000s, colors2000s } from '../../theme/colors'

const currencyFmt = new Intl.NumberFormat('es-AR', {
  style: 'currency',
  currency: 'ARS',
  maximumFractionDigits: 0
})

const statusLabel: Record<string, string> = {
  pending: 'Pendiente',
  pending_payment: 'Pendiente de pago',
  confirmed: 'Confirmado',
  completed: 'Completado',
  cancelled: 'Cancelado',
  absent: 'Ausente',
  expired: 'Vencido'
}

const collectibleStatuses = new Set(['pending', 'pending_payment', 'confirmed'])

const CollectionsPage: React.FC = () => {
  const appointmentsQuery = usePaymentsAppointments()
  const summaryQuery = useReconciliationSummary()
  const createPreference = useCreatePaymentPreference()
  const manualConfirm = useManualConfirmPayment()
  const [message, setMessage] = useState('')

  const cardStyle = {
    background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
    border: `1px solid ${colors2000s.border.default}`,
    boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`
  }

  const appointments = useMemo(
    () =>
      (appointmentsQuery.data ?? [])
        .filter((appointment) => collectibleStatuses.has(appointment.status))
        .slice(0, 20),
    [appointmentsQuery.data]
  )

  const cards = useMemo(() => {
    const summary = summaryQuery.data
    return [
      { label: 'Turnos listados', value: appointments.length },
      { label: 'Pagos pendientes', value: summary?.pending_payments ?? 0 },
      {
        label: 'Monto pendiente',
        value: currencyFmt.format(Number(summary?.total_pending_amount ?? 0))
      }
    ]
  }, [appointments.length, summaryQuery.data])

  const handleCreatePreference = async (appointmentId: string) => {
    try {
      const response = await createPreference.mutateAsync(appointmentId)
      setMessage(`Link de cobro creado: ${response.payment_public_id}`)
    } catch (error: any) {
      setMessage(error.response?.data?.detail || 'No se pudo crear el link de cobro')
    }
  }

  const handleManualConfirm = async (appointmentId: string) => {
    try {
      const response = await manualConfirm.mutateAsync({ appointmentId })
      setMessage(`Pago confirmado manualmente: ${response.public_id}`)
    } catch (error: any) {
      setMessage(error.response?.data?.detail || 'No se pudo confirmar el pago')
    }
  }

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <div
        className="p-6 rounded-3xl flex flex-wrap items-start justify-between gap-4"
        style={cardStyle}
      >
        <div>
          <h2
            className="text-2xl font-black uppercase tracking-tight"
            style={{ color: colors2000s.text.primary }}
          >
            Cobros
          </h2>
          <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Turnos operables para generar links y confirmar pagos manuales sin mezclarlo con
            configuración.
          </p>
        </div>
        {appointmentsQuery.isLoading && (
          <div
            className="flex items-center gap-2 text-xs font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            <Loader2 className="w-4 h-4 animate-spin" />
            Cargando cobros...
          </div>
        )}
      </div>

      {message && (
        <div
          className="p-4 rounded-2xl text-sm font-bold flex items-center gap-3"
          style={{ background: '#fff7ed', border: '1px solid #fed7aa', color: '#c2410c' }}
        >
          <AlertCircle className="w-5 h-5 flex-shrink-0" />
          <span>{message}</span>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {cards.map((card) => (
          <div key={card.label} className="p-5 rounded-2xl" style={cardStyle}>
            <p
              className="text-[10px] font-black uppercase tracking-widest"
              style={{ color: colors2000s.text.secondary }}
            >
              {card.label}
            </p>
            <p className="mt-2 text-2xl font-black" style={{ color: colors2000s.orange.accent }}>
              {card.value}
            </p>
          </div>
        ))}
      </div>

      <div className="p-6 rounded-3xl space-y-4" style={cardStyle}>
        <div className="flex items-center gap-3">
          <CreditCard className="w-5 h-5" style={{ color: colors2000s.orange.accent }} />
          <h3
            className="text-lg font-black uppercase tracking-tight"
            style={{ color: colors2000s.text.primary }}
          >
            Turnos listos para cobrar
          </h3>
        </div>

        <div className="space-y-3">
          {appointments.map((appointment) => {
            const latestLink =
              createPreference.data?.appointment_id === appointment.public_id
                ? createPreference.data.payment_link
                : null

            return (
              <div
                key={appointment.public_id}
                className="rounded-2xl p-4 bg-white flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4"
                style={{
                  border: `1px solid ${colors2000s.border.light}`,
                  boxShadow: colors2000s.shadows.insetDark
                }}
              >
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <p className="text-sm font-black" style={{ color: colors2000s.text.primary }}>
                      {appointment.client_name}
                    </p>
                    <span
                      className="px-2.5 py-1 rounded-full text-[10px] font-black uppercase tracking-widest"
                      style={{
                        background: '#f3f4f6',
                        color: colors2000s.text.secondary,
                        border: `1px solid ${colors2000s.border.light}`
                      }}
                    >
                      {statusLabel[appointment.status] ?? appointment.status}
                    </span>
                  </div>
                  <p
                    className="text-[11px] font-bold mt-1"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    {appointment.service_name} · {appointment.staff_name} ·{' '}
                    {new Date(appointment.starts_at).toLocaleString('es-AR')}
                  </p>
                </div>

                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => handleCreatePreference(appointment.public_id)}
                    className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest inline-flex items-center gap-2"
                    style={buttonStyles2000s.default}
                  >
                    <Link2 className="w-3.5 h-3.5" />
                    Crear link
                  </button>
                  <button
                    type="button"
                    onClick={() => handleManualConfirm(appointment.public_id)}
                    className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest inline-flex items-center gap-2"
                    style={buttonStyles2000s.selected}
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    Confirmar manual
                  </button>
                  {latestLink && (
                    <a
                      href={latestLink}
                      target="_blank"
                      rel="noreferrer"
                      className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest inline-flex items-center gap-2"
                      style={buttonStyles2000s.default}
                    >
                      Abrir link
                      <ExternalLink className="w-3.5 h-3.5" />
                    </a>
                  )}
                </div>
              </div>
            )
          })}

          {!appointments.length && !appointmentsQuery.isLoading && (
            <div
              className="rounded-2xl p-6 bg-white text-sm font-bold"
              style={{
                border: `1px solid ${colors2000s.border.light}`,
                boxShadow: colors2000s.shadows.insetDark,
                color: colors2000s.text.secondary
              }}
            >
              No hay turnos pendientes o confirmados para operar cobros ahora.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default CollectionsPage
