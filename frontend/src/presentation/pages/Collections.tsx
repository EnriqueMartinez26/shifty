import React, { useState } from 'react'

import { CheckCircle2, CreditCard, ExternalLink, Link2 } from 'lucide-react'

import { isCollectibleStatus } from '@domain/value-objects/BookingStatus'

import { getErrorMessage } from '@shared/errors/getErrorMessage'
import { formatCurrency } from '@shared/utils/currency'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { FormFeedback, type FormFeedbackMessage } from '../components/molecules/FormFeedback'
import { PageHeader } from '../components/molecules/PageHeader'
import { QueryErrorNotice } from '../components/molecules/QueryErrorNotice'
import { SummaryCards } from '../components/molecules/SummaryCards'
import { useAuth } from '../context/AuthContext'
import { ROLES_ADMIN_SUPER, hasAnyRole } from '../context/roles'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import {
  useCreatePaymentPreference,
  useManualConfirmPayment,
  usePaymentsAppointments,
  useReconciliationSummary
} from '../hooks/usePayments'
import { useStoreFeatureFlags } from '../hooks/useStores'
import { useStoreWriteAccess } from '../hooks/useStoreWriteAccess'
import { bookingStatusLabel } from '../lib/bookingStatusLabel'
import { formatDateTimeEsAr } from '../lib/formatters'
import { create2000sListCardStyle, create2000sPanelStyle } from '../lib/surfaceStyles'

const PAYMENTS_OFF_REASON =
  'Los cobros online están apagados para tu negocio. Activalos en Configuración > Funciones.'
const PAYMENTS_OFF_NOTICE = `${PAYMENTS_OFF_REASON} Las señas que te pagan por WhatsApp las confirmás igual con "Confirmar pago".`

const CollectionsPage: React.FC = () => {
  useDocumentTitle('Cobros · Shifty')
  const appointmentsQuery = usePaymentsAppointments()
  const { user } = useAuth()
  // La conciliacion es solo de admins (el backend le responde 403 al
  // profesional): sin ella no hay pagos pendientes que mostrarle (FF-21).
  const isAdmin = hasAnyRole(user?.role, ROLES_ADMIN_SUPER, user?.is_global_admin)
  // Con los cobros apagados todo /payments responde 403 (QA 2026-10-02: los
  // botones fallaban y el aviso salia dos veces). Mientras los flags no
  // llegan no se supone nada: el backend sigue siendo la guarda.
  const flagsQuery = useStoreFeatureFlags()
  const paymentsOff = flagsQuery.data?.flags.payments === false
  const summaryQuery = useReconciliationSummary(isAdmin && !paymentsOff)
  const createPreference = useCreatePaymentPreference()
  const manualConfirm = useManualConfirmPayment()
  // Tienda suspendida: crear el link y confirmar el pago responden 402.
  const writeAccess = useStoreWriteAccess()
  const suspendedReason = writeAccess.readOnly ? writeAccess.reason : null
  // El link es de Mercado Pago: necesita los cobros online. Confirmar a mano
  // no (decision de Mateo, 2026-10-03): es como se cierra la seña que el
  // cliente paga por WhatsApp, con o sin Mercado Pago.
  const linkBlockedReason = paymentsOff ? PAYMENTS_OFF_REASON : suspendedReason
  const confirmBlockedReason = suspendedReason
  const [feedback, setFeedback] = useState<FormFeedbackMessage | null>(null)

  const cardStyle = create2000sPanelStyle()

  const appointments = (appointmentsQuery.data ?? [])
    .filter((appointment) => isCollectibleStatus(appointment.status))
    .slice(0, 20)

  const summary = summaryQuery.data
  const cards = [
    { label: 'Turnos listados', value: appointments.length },
    ...(isAdmin
      ? [
          { label: 'Pagos pendientes', value: summary?.pending_payments ?? 0 },
          {
            label: 'Monto pendiente',
            value: formatCurrency(Number(summary?.total_pending_amount ?? 0))
          }
        ]
      : [])
  ]

  const handleCreatePreference = async (appointmentId: string) => {
    try {
      const response = await createPreference.mutateAsync(appointmentId)
      setFeedback({
        tone: 'success',
        text: `Link de cobro creado: ${response.payment_public_id}`
      })
    } catch (error: unknown) {
      setFeedback({
        tone: 'error',
        text: getErrorMessage(error, 'No se pudo crear el link de cobro')
      })
    }
  }

  const handleManualConfirm = async (appointmentId: string) => {
    try {
      const response = await manualConfirm.mutateAsync({ appointmentId })
      setFeedback({ tone: 'success', text: `Pago confirmado manualmente: ${response.public_id}` })
    } catch (error: unknown) {
      setFeedback({ tone: 'error', text: getErrorMessage(error, 'No se pudo confirmar el pago') })
    }
  }

  return (
    <div className="space-y-8 duration-500">
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

      {paymentsOff && (
        <div
          role="status"
          className="p-4 rounded-2xl text-sm font-bold"
          style={{
            background: colors2000s.status.info.bg,
            border: `1px solid ${colors2000s.status.info.border}`,
            color: colors2000s.status.info.text
          }}
        >
          {PAYMENTS_OFF_NOTICE}
        </div>
      )}

      {/* Junto a la accion y a la vista: el aviso de arriba quedaba fuera. */}
      <FormFeedback feedback={feedback} />

      <SummaryCards cards={cards} columns={isAdmin ? 3 : 1} />

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
                    disabled={linkBlockedReason !== null}
                    title={linkBlockedReason ?? undefined}
                    className="px-4 py-2 text-[10px] font-black uppercase tracking-widest inline-flex items-center gap-2 disabled:opacity-50"
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
                    disabled={confirmBlockedReason !== null}
                    title={confirmBlockedReason ?? undefined}
                    className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest inline-flex items-center gap-2 disabled:opacity-50"
                    style={buttonStyles2000s.selected}
                  >
                    <CheckCircle2 className="w-3.5 h-3.5" />
                    Confirmar pago
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
