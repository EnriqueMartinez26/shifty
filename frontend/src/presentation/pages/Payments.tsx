import React, { useRef, useState } from 'react'

import { RefreshCcw, Settings2 } from 'lucide-react'
import { useNavigate } from 'react-router'

import { totalCollected } from '@domain/value-objects/AppointmentCharge'

import { getErrorMessage } from '@shared/errors/getErrorMessage'
import { parseAmountInput } from '@shared/utils/amountInput'
import { formatCurrency } from '@shared/utils/currency'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { MessageBanner } from '../components/molecules/MessageBanner'
import { PageHeader } from '../components/molecules/PageHeader'
import { QueryErrorNotice } from '../components/molecules/QueryErrorNotice'
import { SummaryCards } from '../components/molecules/SummaryCards'
import { useDocumentTitle } from '../hooks/useDocumentTitle'
import {
  useGatewayConfig,
  useOutboxStats,
  useProcessOutbox,
  useReconciliationSummary,
  useRefundPayment
} from '../hooks/usePayments'
import {
  create2000sInputStyle,
  create2000sListCardStyle,
  create2000sPanelStyle
} from '../lib/surfaceStyles'

type RefundScope = 'total' | 'partial'

type RefundReview = {
  paymentId: string
  reason?: string
} & ({ scope: 'total' } | { scope: 'partial'; amount: number })

const preciseAmount = new Intl.NumberFormat('es-AR', {
  style: 'currency',
  currency: 'ARS',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2
})

const PaymentsPage: React.FC = () => {
  useDocumentTitle('Cobros online · Shifty')
  // Navegacion dentro de la SPA: `window.location.assign` recargaba todo y
  // perdia el token en memoria camino a Configuracion (F11b-20).
  const navigate = useNavigate()
  const gatewayQuery = useGatewayConfig()
  const summaryQuery = useReconciliationSummary()
  const outboxStatsQuery = useOutboxStats()
  const refundPayment = useRefundPayment()
  const processOutbox = useProcessOutbox()

  const [refundForm, setRefundForm] = useState({
    paymentId: '',
    scope: '' as RefundScope | '',
    amount: '',
    reason: ''
  })
  const [refundReview, setRefundReview] = useState<RefundReview | null>(null)
  const [refundError, setRefundError] = useState('')
  const [externalRefundConfirmed, setExternalRefundConfirmed] = useState(false)
  const [refundBusy, setRefundBusy] = useState(false)
  const refundSubmitting = useRef(false)
  const [message, setMessage] = useState('')

  const summary = summaryQuery.data
  const summaryCards = [
    { label: 'Por revisar', value: summary?.pending_payments ?? 0 },
    { label: 'Aprobados', value: summary?.approved_payments ?? 0 },
    { label: 'Confirmados manualmente', value: summary?.manual_confirmed_payments ?? 0 },
    {
      label: 'Total cobrado',
      value: formatCurrency(
        totalCollected(summary?.total_approved_amount, summary?.total_remainder_amount)
      )
    }
  ]

  const updateRefundForm = (change: Partial<typeof refundForm>) => {
    setRefundForm((previous) => ({ ...previous, ...change }))
    setRefundReview(null)
    setExternalRefundConfirmed(false)
    setRefundError('')
    setMessage('')
  }

  const prepareRefundReview = () => {
    const paymentId = refundForm.paymentId.trim()
    if (!paymentId) {
      setRefundError('Ingresá el ID del cobro.')
      return
    }
    if (!refundForm.scope) {
      setRefundError('Elegí si la devolución fue total o parcial.')
      return
    }
    const reason = refundForm.reason.trim() || undefined
    if (refundForm.scope === 'partial') {
      // 2026-10-16: Number('3.200') registraba 3,20 y Number('3.200,50')
      // enviaba NaN, que podia terminar interpretado como devolucion total.
      const parsed = parseAmountInput(refundForm.amount)
      if (!parsed.ok) {
        setRefundError(parsed.error)
        return
      }
      if (!Number.isFinite(parsed.value) || !Number.isSafeInteger(Math.round(parsed.value * 100))) {
        setRefundError('El importe es demasiado grande para registrarlo con precisión.')
        return
      }
      setRefundReview({ paymentId, scope: 'partial', amount: parsed.value, reason })
    } else {
      setRefundReview({ paymentId, scope: 'total', reason })
    }
    setRefundError('')
    setMessage('')
    setExternalRefundConfirmed(false)
  }

  const handleRefund = async () => {
    if (!refundReview || !externalRefundConfirmed || refundSubmitting.current) return
    refundSubmitting.current = true
    setRefundBusy(true)
    try {
      const response = await refundPayment.mutateAsync({
        paymentId: refundReview.paymentId,
        amount: refundReview.scope === 'partial' ? refundReview.amount : undefined,
        reason: refundReview.reason,
        manual: true
      })
      // La devolucion no revierte el resto del turno (D-20261008-01).
      const resto = response.live_remainder_amount
      setMessage(
        resto
          ? `Devolución registrada: ${response.public_id}. Hay un resto de ${formatCurrency(Number(resto))} registrado en ese turno; revertilo desde Cobros si también lo devolviste.`
          : `Devolución registrada: ${response.public_id}`
      )
      setRefundForm({ paymentId: '', scope: '', amount: '', reason: '' })
      setRefundReview(null)
      setExternalRefundConfirmed(false)
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, 'No se pudo registrar la devolución'))
    } finally {
      refundSubmitting.current = false
      setRefundBusy(false)
    }
  }

  const handleProcessOutbox = async () => {
    try {
      const response = await processOutbox.mutateAsync(100)
      setMessage(`Actualización completada: ${response.processed} cobros revisados`)
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, 'No se pudo actualizar el estado de los cobros'))
    }
  }

  const cardStyle = create2000sPanelStyle()
  const inputStyle = create2000sInputStyle()

  return (
    <div className="space-y-8 duration-500">
      <PageHeader
        title="Cobros online"
        description="Configurá el cobro online, revisá el estado de los pagos y registrá devoluciones."
        isLoading={gatewayQuery.isLoading || summaryQuery.isLoading}
        loadingText="Cargando cobros online..."
      />

      <QueryErrorNotice
        error={gatewayQuery.error ?? summaryQuery.error ?? outboxStatsQuery.error}
        message="No se pudieron cargar los cobros online."
      />

      <MessageBanner message={message} />

      <SummaryCards cards={summaryCards} columns={4} />

      <div className="grid grid-cols-1 xl:grid-cols-[1.1fr_0.9fr] gap-6">
        <div className="p-6 rounded-3xl space-y-5" style={cardStyle}>
          <div className="flex items-center justify-between gap-4">
            <h3
              className="text-lg font-black uppercase tracking-tight"
              style={{ color: colors2000s.text.primary }}
            >
              Integración de cobros
            </h3>
            <span
              className="px-3 py-1.5 rounded-full text-[10px] font-black uppercase tracking-widest"
              style={{
                background: gatewayQuery.data?.configured
                  ? colors2000s.status.success.bg
                  : colors2000s.status.warning.bg,
                color: gatewayQuery.data?.configured
                  ? colors2000s.status.success.text
                  : colors2000s.status.warning.text
              }}
            >
              {gatewayQuery.data?.configured ? 'Conectada' : 'Sin conectar'}
            </span>
          </div>

          <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            La cuenta de Mercado Pago se conecta desde Configuración de tienda. Shifty nunca te pide
            ni muestra tus claves de Mercado Pago.
          </p>
          <button
            type="button"
            onClick={() => void navigate('/dashboard/settings?tab=payments')}
            className="w-full py-3 text-xs font-black uppercase tracking-widest"
            style={buttonStyles2000s.default}
          >
            Abrir configuración de Mercado Pago
          </button>
        </div>

        <div className="p-6 rounded-3xl space-y-5" style={cardStyle}>
          <div className="flex items-center justify-between">
            <h3
              className="text-lg font-black uppercase tracking-tight"
              style={{ color: colors2000s.text.primary }}
            >
              Estado de sincronización
            </h3>
            <button
              type="button"
              onClick={() => {
                void handleProcessOutbox()
              }}
              className="px-4 py-2 text-xs font-black uppercase tracking-widest"
              style={buttonStyles2000s.default}
            >
              <RefreshCcw className="w-4 h-4 inline mr-2" />
              Actualizar cobros
            </button>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="rounded-2xl p-4 bg-white" style={create2000sListCardStyle()}>
              <p
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Por revisar
              </p>
              <p className="mt-2 text-xl font-black" style={{ color: colors2000s.orange.accent }}>
                {outboxStatsQuery.data?.pending ?? 0}
              </p>
            </div>
            <div className="rounded-2xl p-4 bg-white" style={create2000sListCardStyle()}>
              <p
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Con error
              </p>
              <p
                className="mt-2 text-xl font-black"
                style={{ color: colors2000s.status.danger.light }}
              >
                {outboxStatsQuery.data?.pending_with_error ?? 0}
              </p>
            </div>
            <div className="rounded-2xl p-4 bg-white" style={create2000sListCardStyle()}>
              <p
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Actualizados
              </p>
              <p
                className="mt-2 text-xl font-black"
                style={{ color: colors2000s.status.success.dark }}
              >
                {outboxStatsQuery.data?.processed ?? 0}
              </p>
            </div>
          </div>

          <div className="space-y-3">
            <h3
              className="text-[10px] font-black uppercase tracking-widest"
              style={{ color: colors2000s.text.secondary }}
            >
              Devolución manual
            </h3>
            <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
              Shifty registra una devolución que ya hiciste por fuera. No transfiere dinero ni
              inicia un reembolso en Mercado Pago.
            </p>
            <label htmlFor="refund-payment-id" className="block text-xs font-bold">
              ID del cobro
            </label>
            <input
              id="refund-payment-id"
              value={refundForm.paymentId}
              onChange={(e) => updateRefundForm({ paymentId: e.target.value })}
              disabled={refundBusy}
              className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
              style={inputStyle}
              placeholder="ID del cobro"
            />
            <fieldset disabled={refundBusy} className="space-y-2">
              <legend className="text-xs font-bold">¿Cuánto devolviste?</legend>
              <label className="flex items-center gap-2 text-xs font-bold">
                <input
                  type="radio"
                  name="refund-scope"
                  value="total"
                  checked={refundForm.scope === 'total'}
                  onChange={() => updateRefundForm({ scope: 'total', amount: '' })}
                />
                Total: todo el importe del cobro
              </label>
              <label className="flex items-center gap-2 text-xs font-bold">
                <input
                  type="radio"
                  name="refund-scope"
                  value="partial"
                  checked={refundForm.scope === 'partial'}
                  onChange={() => updateRefundForm({ scope: 'partial' })}
                />
                Parcial: un importe específico
              </label>
            </fieldset>
            {refundForm.scope === 'partial' && (
              <>
                <label htmlFor="refund-amount" className="block text-xs font-bold">
                  Importe devuelto en pesos
                </label>
                <input
                  id="refund-amount"
                  type="text"
                  inputMode="decimal"
                  value={refundForm.amount}
                  onChange={(e) => updateRefundForm({ amount: e.target.value })}
                  disabled={refundBusy}
                  className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                  style={inputStyle}
                  placeholder="Ejemplo: 3.200,50"
                  aria-describedby="refund-amount-help"
                />
                <p id="refund-amount-help" className="text-xs font-bold">
                  Usá punto para miles y coma para centavos.
                </p>
              </>
            )}
            <label htmlFor="refund-reason" className="block text-xs font-bold">
              Motivo de la devolución (opcional)
            </label>
            <textarea
              id="refund-reason"
              value={refundForm.reason}
              onChange={(e) => updateRefundForm({ reason: e.target.value })}
              disabled={refundBusy}
              maxLength={500}
              className="w-full min-h-24 rounded-2xl px-4 py-3 font-bold outline-none resize-y"
              style={inputStyle}
              placeholder="Motivo de la devolución"
            />
            {refundError && <p role="alert">{refundError}</p>}
            <button
              type="button"
              onClick={prepareRefundReview}
              disabled={refundBusy}
              className="w-full px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest disabled:opacity-50"
              style={buttonStyles2000s.selected}
            >
              Revisar devolución
            </button>
            {refundReview && (
              <div
                className="space-y-3 rounded-2xl bg-white p-4"
                style={create2000sListCardStyle()}
              >
                <h4 className="text-sm font-black">Revisá antes de registrar</h4>
                <p className="text-xs font-bold">Cobro: {refundReview.paymentId}</p>
                <p className="text-xs font-bold">
                  Devolución:{' '}
                  {refundReview.scope === 'total'
                    ? 'total del cobro, según el importe registrado en Shifty'
                    : `parcial de ${preciseAmount.format(refundReview.amount)}`}
                </p>
                <p className="text-xs font-bold">
                  El cobro quedará marcado como devuelto. Esta acción no envía dinero y no admite
                  registrar otra devolución sobre el mismo cobro.
                </p>
                <label className="flex items-start gap-2 text-xs font-bold">
                  <input
                    type="checkbox"
                    checked={externalRefundConfirmed}
                    onChange={(event) => setExternalRefundConfirmed(event.target.checked)}
                    disabled={refundBusy}
                  />
                  Confirmo que ya hice esta devolución por fuera de Shifty.
                </label>
                <button
                  type="button"
                  onClick={() => void handleRefund()}
                  disabled={!externalRefundConfirmed || refundBusy}
                  className="w-full px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest disabled:opacity-50"
                  style={buttonStyles2000s.selected}
                >
                  {refundBusy ? 'Registrando devolución...' : 'Confirmar registro de devolución'}
                </button>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="p-6 rounded-3xl space-y-4" style={cardStyle}>
        <div className="flex items-center gap-3">
          <Settings2 className="w-5 h-5" style={{ color: colors2000s.orange.accent }} />
          <div>
            <h3
              className="text-lg font-black uppercase tracking-tight"
              style={{ color: colors2000s.text.primary }}
            >
              Otras secciones
            </h3>
            <p className="text-[11px] font-bold" style={{ color: colors2000s.text.secondary }}>
              Las promociones y los turnos por cobrar tienen su propia sección en el menú lateral.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default PaymentsPage
