import React, { useMemo, useState } from 'react'

import { CheckCircle2, CreditCard, ExternalLink, Link2 } from 'lucide-react'

import { isCollectibleStatus } from '@domain/value-objects/BookingStatus'

import { getErrorMessage } from '@shared/errors/getErrorMessage'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { MessageBanner } from '../components/molecules/MessageBanner'
import { PageHeader } from '../components/molecules/PageHeader'
import { QueryErrorNotice } from '../components/molecules/QueryErrorNotice'
import { SummaryCards } from '../components/molecules/SummaryCards'
import {
  useCreatePaymentPreference,
  useManualConfirmPayment,
  usePaymentsAppointments,
  useReconciliationSummary
} from '../hooks/usePayments'
import { bookingStatusLabel } from '../lib/bookingStatusLabel'
import { currencyFmtEsAr as currencyFmt, formatDateTimeEsAr } from '../lib/formatters'
import { create2000sListCardStyle, create2000sPanelStyle } from '../lib/surfaceStyles'

const CollectionsPage: React.FC = () => {
  const appointmentsQuery = usePaymentsAppointments()
  const summaryQuery = useReconciliationSummary()
  const createPreference = useCreatePaymentPreference()
  const manualConfirm = useManualConfirmPayment()
  const [message, setMessage] = useState('')

  const cardStyle = create2000sPanelStyle()

  const appointments = useMemo(
    () =>
      (appointmentsQuery.data ?? [])
        .filter((appointment) => isCollectibleStatus(appointment.status))
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
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, 'No se pudo crear el link de cobro'))
    }
  }

  const handleManualConfirm = async (appointmentId: string) => {
    try {
      const response = await manualConfirm.mutateAsync({ appointmentId })
      setMessage(`Pago confirmado manualmente: ${response.public_id}`)
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, 'No se pudo confirmar el pago'))
    }
  }

  return (
    <div className="space-y-8 animate-in fade-in duration-500">
      <PageHeader
        title="Cobros"
        description="Turnos operables para generar links y confirmar pagos manuales sin mezclarlo con configuración."
        isLoading={appointmentsQuery.isLoading}
        loadingText="Cargando cobros..."
      />

      <QueryErrorNotice
        error={appointmentsQuery.error ?? summaryQuery.error}
        message="No se pudieron cargar los cobros."
      />

      <MessageBanner message={message} />

      <SummaryCards cards={cards} columns={3} />

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
                style={create2000sListCardStyle()}
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
                        color: colors2000s.text.secondary
                      }}
                    >
                      {bookingStatusLabel(appointment.status)}
                    </span>
                  </div>
                  <p
                    className="text-[11px] font-bold mt-1"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    {appointment.service_name} · {appointment.staff_name} ·{' '}
                    {formatDateTimeEsAr(appointment.starts_at)}
                  </p>
                </div>

                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      void handleCreatePreference(appointment.public_id)
                    }}
                    className="px-4 py-2 text-[10px] font-black uppercase tracking-widest inline-flex items-center gap-2"
                    style={buttonStyles2000s.default}
                  >
                    <Link2 className="w-3.5 h-3.5" />
                    Crear link
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      void handleManualConfirm(appointment.public_id)
                    }}
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
                      className="px-4 py-2 text-[10px] font-black uppercase tracking-widest inline-flex items-center gap-2"
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
              style={{ ...create2000sListCardStyle(), color: colors2000s.text.secondary }}
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
