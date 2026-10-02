import React, { useState } from 'react'

import { RefreshCcw, Settings2 } from 'lucide-react'
import { useNavigate } from 'react-router'

import { getErrorMessage } from '@shared/errors/getErrorMessage'
import { formatCurrency } from '@shared/utils/currency'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { MessageBanner } from '../components/molecules/MessageBanner'
import { PageHeader } from '../components/molecules/PageHeader'
import { QueryErrorNotice } from '../components/molecules/QueryErrorNotice'
import { SummaryCards } from '../components/molecules/SummaryCards'
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

const PaymentsPage: React.FC = () => {
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
    amount: '',
    reason: ''
  })
  const [message, setMessage] = useState('')

  const summary = summaryQuery.data
  const summaryCards = [
    { label: 'Por revisar', value: summary?.pending_payments ?? 0 },
    { label: 'Aprobados', value: summary?.approved_payments ?? 0 },
    { label: 'Confirmados manualmente', value: summary?.manual_confirmed_payments ?? 0 },
    {
      label: 'Total cobrado',
      value: formatCurrency(Number(summary?.total_approved_amount ?? 0))
    }
  ]

  const handleRefund = async () => {
    try {
      const response = await refundPayment.mutateAsync({
        paymentId: refundForm.paymentId,
        amount: refundForm.amount ? Number(refundForm.amount) : undefined,
        reason: refundForm.reason || undefined,
        manual: true
      })
      setMessage(`Devolución registrada: ${response.public_id}`)
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, 'No se pudo registrar la devolución'))
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
                style={{ color: colors2000s.text.disabled }}
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
                style={{ color: colors2000s.text.disabled }}
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
                style={{ color: colors2000s.text.disabled }}
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
            <label
              className="text-[10px] font-black uppercase tracking-widest"
              style={{ color: colors2000s.text.secondary }}
            >
              Devolución manual
            </label>
            <input
              value={refundForm.paymentId}
              onChange={(e) => setRefundForm((prev) => ({ ...prev, paymentId: e.target.value }))}
              className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
              style={inputStyle}
              placeholder="ID del cobro"
            />
            <input
              value={refundForm.amount}
              onChange={(e) => setRefundForm((prev) => ({ ...prev, amount: e.target.value }))}
              className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
              style={inputStyle}
              placeholder="Monto opcional"
            />
            <textarea
              value={refundForm.reason}
              onChange={(e) => setRefundForm((prev) => ({ ...prev, reason: e.target.value }))}
              className="w-full min-h-24 rounded-2xl px-4 py-3 font-bold outline-none resize-y"
              style={inputStyle}
              placeholder="Motivo de la devolución"
            />
            <button
              type="button"
              onClick={() => {
                void handleRefund()
              }}
              disabled={!refundForm.paymentId}
              className="w-full px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest disabled:opacity-50"
              style={buttonStyles2000s.selected}
            >
              Registrar devolución
            </button>
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
