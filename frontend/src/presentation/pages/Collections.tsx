import React, { useState } from 'react'

import { CreditCard } from 'lucide-react'

import {
  appointmentChargeOf,
  type AppointmentCharge,
  type RemainderPaymentMethod
} from '@domain/value-objects/AppointmentCharge'
import { isCollectibleStatus } from '@domain/value-objects/BookingStatus'

import type { AppointmentSearchItem } from '@application/services/PaymentsService'

import { getErrorMessage } from '@shared/errors/getErrorMessage'
import { formatCurrency } from '@shared/utils/currency'
import { createUuid } from '@shared/utils/uuid'

import { colors2000s } from '../../theme/colors'
import { CollectionAppointmentCard } from '../components/molecules/CollectionAppointmentCard'
import { FormFeedback, type FormFeedbackMessage } from '../components/molecules/FormFeedback'
import { PageHeader } from '../components/molecules/PageHeader'
import { QueryErrorNotice } from '../components/molecules/QueryErrorNotice'
import { SummaryCards } from '../components/molecules/SummaryCards'
import { ManualPaymentModal } from '../components/organisms/ManualPaymentModal'
import { useAuth } from '../context/AuthContext'
import { ROLES_ADMIN_SUPER, hasAnyRole } from '../context/roles'
import { useConfirm } from '../hooks/useConfirm'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import {
  useCreatePaymentPreference,
  useManualConfirmPayment,
  usePaymentsAppointments,
  useReconciliationSummary,
  useRecordRemainingPayment,
  useRevertRemainingPayment
} from '../hooks/usePayments'
import { useStoreFeatureFlags } from '../hooks/useStores'
import { useStoreWriteAccess } from '../hooks/useStoreWriteAccess'
import { create2000sListCardStyle, create2000sPanelStyle } from '../lib/surfaceStyles'

const PAYMENTS_OFF_REASON =
  'Los cobros online están apagados para tu negocio. Activalos en Configuración > Funciones.'
const PAYMENTS_OFF_NOTICE = `${PAYMENTS_OFF_REASON} Las señas que te pagan por WhatsApp las confirmás igual con "Confirmar pago".`

const chargeOf = (appointment: AppointmentSearchItem): AppointmentCharge =>
  appointmentChargeOf({
    appointmentStatus: appointment.status,
    priceAmount: appointment.price_amount,
    paymentStatus: appointment.payment_status,
    paymentAmount: appointment.payment_amount,
    remainingAmount: appointment.remaining_amount,
    remainderAmount: appointment.remainder_payment?.amount
  })

/** Lo que resta del turno, para precargar y topear el dialogo del resto. */
const remainingOf = (charge: AppointmentCharge): number =>
  charge.kind === 'paid' ? charge.remaining : 0

/** Importe que el dialogo precarga: el cobro pendiente o el precio del turno. */
const suggestedAmountOf = (charge: AppointmentCharge): number | null => {
  if (charge.kind === 'pending') return charge.amount
  if (charge.kind === 'unpaid') return charge.suggested
  return null
}

/**
 * Importe que viaja al confirmar. Sin `amount` el backend registra el importe
 * del cobro VIVO, venga de donde venga, sin re-tarifarlo (promo y snapshot de
 * la sena intactos). Sin cobro vivo no hay importe que conservar: se manda
 * siempre el que se mostro, asi lo registrado es lo que se vio (revision de
 * la PR #131, C1: el backend solo conservaba los cobros con sena y un link
 * del panel se registraba por el precio del turno).
 */
const amountToSend = (charge: AppointmentCharge, amount: number): number | undefined =>
  charge.kind === 'pending' && amount === charge.amount ? undefined : amount

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
  // Turno cuyo pago se esta confirmando (dialogo abierto) y su error.
  const [paying, setPaying] = useState<AppointmentSearchItem | null>(null)
  const [payError, setPayError] = useState<string | null>(null)
  // Saldo restante por turno (D-20261008-01): turno cuyo resto se registra,
  // su error y la clave de idempotencia del dialogo (un reintento del mismo
  // envio no registra dos restos).
  const recordRemainder = useRecordRemainingPayment()
  const revertRemainder = useRevertRemainingPayment()
  const { confirm, confirmDialog } = useConfirm()
  const [remainderFor, setRemainderFor] = useState<AppointmentSearchItem | null>(null)
  const [remainderError, setRemainderError] = useState<string | null>(null)
  const [remainderKey, setRemainderKey] = useState('')

  const cardStyle = create2000sPanelStyle()

  // Un completado o un ausente se sigue cobrando (regla 3): solo un turno
  // soltado (cancelado o vencido) sale de la lista.
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

  // Los avisos nombran al cliente, nunca un id (regla 20).
  const handleCreatePreference = async (appointment: AppointmentSearchItem) => {
    try {
      await createPreference.mutateAsync(appointment.public_id)
      setFeedback({
        tone: 'success',
        text: `Link de cobro creado para ${appointment.client_name}.`
      })
    } catch (error: unknown) {
      setFeedback({
        tone: 'error',
        text: getErrorMessage(error, 'No se pudo crear el link de cobro')
      })
    }
  }

  const openManualConfirm = (appointment: AppointmentSearchItem) => {
    setPayError(null)
    setPaying(appointment)
  }

  const handleManualConfirm = async (amount: number) => {
    if (!paying) return
    try {
      const response = await manualConfirm.mutateAsync({
        appointmentId: paying.public_id,
        amount: amountToSend(chargeOf(paying), amount)
      })
      setFeedback({
        tone: 'success',
        text: `Pago registrado: ${formatCurrency(response.amount)} de ${paying.client_name}.`
      })
      setPaying(null)
    } catch (error: unknown) {
      setPayError(getErrorMessage(error, 'No se pudo registrar el pago'))
    }
  }

  const openRemainder = (appointment: AppointmentSearchItem) => {
    setRemainderError(null)
    setRemainderKey(createUuid())
    setRemainderFor(appointment)
  }

  const handleRecordRemainder = async (
    amount: number,
    method: RemainderPaymentMethod | null = null
  ) => {
    if (!remainderFor) return
    try {
      const response = await recordRemainder.mutateAsync({
        appointmentId: remainderFor.public_id,
        amount,
        method,
        idempotencyKey: remainderKey
      })
      setFeedback({
        tone: 'success',
        text: `Resto registrado: ${formatCurrency(Number(response.amount))} de ${remainderFor.client_name}.`
      })
      setRemainderFor(null)
    } catch (error: unknown) {
      setRemainderError(getErrorMessage(error, 'No se pudo registrar el resto'))
    }
  }

  // Solo admin (el backend responde 403 al resto). La devolucion se hace por
  // fuera: aca solo se marca el resto como revertido.
  const handleRevertRemainder = async (appointment: AppointmentSearchItem) => {
    const confirmed = await confirm(
      `¿Revertir el resto que pagó ${appointment.client_name}? Hacé la devolución por fuera de Shifty; el turno vuelve a quedar con saldo pendiente.`,
      { confirmLabel: 'Sí, revertir', cancelLabel: 'Volver' }
    )
    if (!confirmed) return
    try {
      await revertRemainder.mutateAsync(appointment.public_id)
      setFeedback({ tone: 'success', text: `Resto revertido de ${appointment.client_name}.` })
    } catch (error: unknown) {
      setFeedback({ tone: 'error', text: getErrorMessage(error, 'No se pudo revertir el resto') })
    }
  }

  const payingCharge = paying ? chargeOf(paying) : null
  const remainderCharge = remainderFor ? chargeOf(remainderFor) : null

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
          {appointments.map((appointment) => (
            <CollectionAppointmentCard
              key={appointment.public_id}
              clientName={appointment.client_name}
              serviceName={appointment.service_name}
              staffName={appointment.staff_name}
              startsAt={appointment.starts_at}
              status={appointment.status}
              charge={chargeOf(appointment)}
              latestLink={
                createPreference.data?.appointment_id === appointment.public_id
                  ? (createPreference.data.payment_link ?? null)
                  : null
              }
              linkBlockedReason={linkBlockedReason}
              confirmBlockedReason={confirmBlockedReason}
              remainderBlockedReason={suspendedReason}
              onCreateLink={() => {
                void handleCreatePreference(appointment)
              }}
              onConfirmPayment={() => openManualConfirm(appointment)}
              onRecordRemainder={() => openRemainder(appointment)}
              onRevertRemainder={
                isAdmin
                  ? () => {
                      void handleRevertRemainder(appointment)
                    }
                  : null
              }
            />
          ))}

          {!appointments.length && !appointmentsQuery.isLoading && (
            <div
              className="rounded-2xl p-6 bg-white text-sm font-bold"
              style={{ ...create2000sListCardStyle(), color: colors2000s.text.secondary }}
            >
              No hay turnos para cobrar ahora.
            </div>
          )}
        </div>
      </div>

      {paying && payingCharge && (
        <ManualPaymentModal
          clientName={paying.client_name}
          serviceName={paying.service_name}
          startsAt={paying.starts_at}
          suggestedAmount={suggestedAmountOf(payingCharge)}
          isDeposit={payingCharge.kind === 'pending' && payingCharge.isDeposit}
          busy={manualConfirm.isPending}
          error={payError}
          onSubmit={(amount) => {
            void handleManualConfirm(amount)
          }}
          onClose={() => setPaying(null)}
        />
      )}

      {remainderFor && remainderCharge && (
        <ManualPaymentModal
          mode="remainder"
          clientName={remainderFor.client_name}
          serviceName={remainderFor.service_name}
          startsAt={remainderFor.starts_at}
          suggestedAmount={remainingOf(remainderCharge)}
          maxAmount={remainingOf(remainderCharge)}
          isDeposit={false}
          busy={recordRemainder.isPending}
          error={remainderError}
          onSubmit={(amount, method) => {
            void handleRecordRemainder(amount, method ?? null)
          }}
          onClose={() => setRemainderFor(null)}
        />
      )}

      {confirmDialog}
    </div>
  )
}

export default CollectionsPage
