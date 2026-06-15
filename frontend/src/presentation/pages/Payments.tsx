import React, { useEffect, useMemo, useState } from 'react'

import { AlertCircle, Loader2, RefreshCcw, Save, Settings2 } from 'lucide-react'

import { getErrorMessage } from '@shared/errors/getErrorMessage'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import {
  useGatewayConfig,
  useOutboxStats,
  useProcessOutbox,
  useReconciliationSummary,
  useRefundPayment,
  useUpsertGatewayConfig
} from '../hooks/usePayments'
import { currencyFmtEsAr as currencyFmt } from '../lib/formatters'
import {
  create2000sInputStyle,
  create2000sListCardStyle,
  create2000sPanelStyle
} from '../lib/surfaceStyles'

const PaymentsPage: React.FC = () => {
  const gatewayQuery = useGatewayConfig()
  const summaryQuery = useReconciliationSummary()
  const outboxStatsQuery = useOutboxStats()
  const upsertGateway = useUpsertGatewayConfig()
  const refundPayment = useRefundPayment()
  const processOutbox = useProcessOutbox()

  const [gatewayForm, setGatewayForm] = useState({
    provider: 'mercadopago' as 'mercadopago' | 'stripe',
    access_token: '',
    public_key: '',
    webhook_secret: ''
  })
  const [refundForm, setRefundForm] = useState({
    paymentId: '',
    amount: '',
    reason: ''
  })
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (gatewayQuery.data) {
      setGatewayForm((prev) => ({
        ...prev,
        provider: (gatewayQuery.data.provider as 'mercadopago' | 'stripe') || 'mercadopago',
        public_key: gatewayQuery.data.public_key || ''
      }))
    }
  }, [gatewayQuery.data])

  const summaryCards = useMemo(() => {
    const summary = summaryQuery.data
    return [
      { label: 'Por revisar', value: summary?.pending_payments ?? 0 },
      { label: 'Aprobados', value: summary?.approved_payments ?? 0 },
      { label: 'Confirmados manualmente', value: summary?.manual_confirmed_payments ?? 0 },
      {
        label: 'Total cobrado',
        value: currencyFmt.format(Number(summary?.total_approved_amount ?? 0))
      }
    ]
  }, [summaryQuery.data])

  const handleSaveGateway = async () => {
    try {
      const response = await upsertGateway.mutateAsync({
        ...gatewayForm,
        access_token: gatewayForm.access_token.trim() || undefined
      })
      setMessage(`Cobros online configurados: ${response.provider}`)
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, 'No se pudo guardar la configuracion'))
    }
  }

  const handleRefund = async () => {
    try {
      const response = await refundPayment.mutateAsync({
        paymentId: refundForm.paymentId,
        amount: refundForm.amount ? Number(refundForm.amount) : undefined,
        reason: refundForm.reason || undefined,
        manual: true
      })
      setMessage(`Devolucion registrada: ${response.public_id}`)
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, 'No se pudo registrar la devolucion'))
    }
  }

  const handleProcessOutbox = async () => {
    try {
      const response = await processOutbox.mutateAsync(100)
      setMessage(`Actualizacion completada: ${response.processed} cobros revisados`)
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, 'No se pudo actualizar el estado de los cobros'))
    }
  }

  const cardStyle = create2000sPanelStyle()
  const inputStyle = create2000sInputStyle()

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
            Cobros online
          </h2>
          <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Configura el cobro online, revisa el estado de los pagos y registra devoluciones.
          </p>
        </div>
        {(gatewayQuery.isLoading || summaryQuery.isLoading) && (
          <div
            className="flex items-center gap-2 text-xs font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            <Loader2 className="w-4 h-4 animate-spin" />
            Cargando cobros online...
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

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        {summaryCards.map((card) => (
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

      <div className="grid grid-cols-1 xl:grid-cols-[1.1fr_0.9fr] gap-6">
        <div className="p-6 rounded-3xl space-y-5" style={cardStyle}>
          <div className="flex items-center justify-between">
            <h3
              className="text-lg font-black uppercase tracking-tight"
              style={{ color: colors2000s.text.primary }}
            >
              Integracion de cobros
            </h3>
          <button
            type="button"
            onClick={() => {
              void handleSaveGateway()
            }}
            className="px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest"
            style={buttonStyles2000s.selected}
          >
              <Save className="w-4 h-4 inline mr-2" />
              Guardar
            </button>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Proveedor
              </label>
              <select
                value={gatewayForm.provider}
                onChange={(e) =>
                  setGatewayForm((prev) => ({
                    ...prev,
                    provider: e.target.value as 'mercadopago' | 'stripe'
                  }))
                }
                className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                style={inputStyle}
              >
                <option value="mercadopago">Mercado Pago</option>
                <option value="stripe">Stripe</option>
              </select>
            </div>
            <div className="space-y-2">
              <label
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Clave publica
              </label>
              <input
                value={gatewayForm.public_key}
                onChange={(e) =>
                  setGatewayForm((prev) => ({ ...prev, public_key: e.target.value }))
                }
                className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                style={inputStyle}
                placeholder="APP_USR..."
              />
            </div>
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <div className="space-y-2">
              <label
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Token privado
              </label>
              <input
                value={gatewayForm.access_token}
                onChange={(e) =>
                  setGatewayForm((prev) => ({ ...prev, access_token: e.target.value }))
                }
                className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                style={inputStyle}
                placeholder={gatewayQuery.data?.configured ? '********' : 'Ingresa el token'}
              />
            </div>
            <div className="space-y-2">
              <label
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Clave de notificaciones
              </label>
              <input
                value={gatewayForm.webhook_secret}
                onChange={(e) =>
                  setGatewayForm((prev) => ({ ...prev, webhook_secret: e.target.value }))
                }
                className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
                style={inputStyle}
                placeholder="Opcional"
              />
            </div>
          </div>

          <p
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            Estado actual: {gatewayQuery.data?.configured ? 'listo para cobrar' : 'sin configurar'}
          </p>
        </div>

        <div className="p-6 rounded-3xl space-y-5" style={cardStyle}>
          <div className="flex items-center justify-between">
            <h3
              className="text-lg font-black uppercase tracking-tight"
              style={{ color: colors2000s.text.primary }}
            >
              Estado de sincronizacion
            </h3>
          <button
            type="button"
            onClick={() => {
              void handleProcessOutbox()
            }}
            className="px-4 py-2 rounded-xl text-xs font-black uppercase tracking-widest"
            style={buttonStyles2000s.default}
          >
              <RefreshCcw className="w-4 h-4 inline mr-2" />
              Actualizar cobros
            </button>
          </div>

          <div className="grid grid-cols-3 gap-3">
            <div
              className="rounded-2xl p-4 bg-white"
              style={create2000sListCardStyle()}
            >
              <p className="text-[10px] font-black uppercase tracking-widest text-gray-400">
                Por revisar
              </p>
              <p className="mt-2 text-xl font-black" style={{ color: colors2000s.orange.accent }}>
                {outboxStatsQuery.data?.pending ?? 0}
              </p>
            </div>
            <div
              className="rounded-2xl p-4 bg-white"
              style={create2000sListCardStyle()}
            >
              <p className="text-[10px] font-black uppercase tracking-widest text-gray-400">
                Con error
              </p>
              <p className="mt-2 text-xl font-black text-red-500">
                {outboxStatsQuery.data?.pending_with_error ?? 0}
              </p>
            </div>
            <div
              className="rounded-2xl p-4 bg-white"
              style={create2000sListCardStyle()}
            >
              <p className="text-[10px] font-black uppercase tracking-widest text-gray-400">
                Actualizados
              </p>
              <p className="mt-2 text-xl font-black text-green-600">
                {outboxStatsQuery.data?.processed ?? 0}
              </p>
            </div>
          </div>

          <div className="space-y-3">
            <label
              className="text-[10px] font-black uppercase tracking-widest"
              style={{ color: colors2000s.text.secondary }}
            >
              Devolucion manual
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
              placeholder="Motivo de la devolucion"
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
              Registrar devolucion
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
              Flujo separado
            </h3>
            <p className="text-[11px] font-bold" style={{ color: colors2000s.text.secondary }}>
              Las promociones y los turnos por cobrar ahora viven en sus propias secciones del menu
              lateral.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

export default PaymentsPage
