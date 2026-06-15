import React, { useEffect, useMemo, useState } from 'react'

import { AlertCircle, Loader2, WalletCards } from 'lucide-react'

import { getErrorMessage } from '@shared/errors/getErrorMessage'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { useAddLedgerMovement, useCustomerLedger, useLedgerSummary } from '../hooks/useLedger'
import { useManagedUsers } from '../hooks/useManagedUsers'
import { currencyFmtEsAr as currencyFmt } from '../lib/formatters'
import { create2000sListCardStyle } from '../lib/surfaceStyles'

const movementTypeLabels: Record<'charge' | 'payment' | 'adjustment' | 'refund', string> = {
  charge: 'Cargo',
  payment: 'Pago',
  adjustment: 'Ajuste',
  refund: 'Devolucion'
}

const LedgerPage: React.FC = () => {
  const usersQuery = useManagedUsers(true)
  const summaryQuery = useLedgerSummary()
  const addMovement = useAddLedgerMovement()
  const clients = useMemo(
    () => (usersQuery.data || []).filter((user) => user.role === 'client' && user.is_active),
    [usersQuery.data]
  )
  const [selectedClientId, setSelectedClientId] = useState<string | null>(null)
  const ledgerQuery = useCustomerLedger(selectedClientId)
  const [movementForm, setMovementForm] = useState({
    movement_type: 'charge' as 'charge' | 'payment' | 'adjustment' | 'refund',
    amount: '',
    appointment_id: '',
    notes: ''
  })
  const [message, setMessage] = useState('')

  useEffect(() => {
    if (!selectedClientId && clients.length > 0) {
      setSelectedClientId(clients[0].public_id)
    }
  }, [clients, selectedClientId])

  const inputStyle = {
    background: 'white',
    border: `1px solid ${colors2000s.border.default}`,
    boxShadow: colors2000s.shadows.insetDark,
    color: colors2000s.text.primary
  }
  const cardStyle = {
    background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
    border: `1px solid ${colors2000s.border.default}`,
    boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerMedium}`
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!selectedClientId) return
    try {
      await addMovement.mutateAsync({
        clientId: selectedClientId,
        payload: {
          movement_type: movementForm.movement_type,
          amount: Number(movementForm.amount),
          appointment_id: movementForm.appointment_id || undefined,
          notes: movementForm.notes || undefined
        }
      })
      setMovementForm({ movement_type: 'charge', amount: '', appointment_id: '', notes: '' })
      setMessage('Movimiento registrado')
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, 'No se pudo registrar el movimiento'))
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
            Cuentas pendientes
          </h2>
          <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
            Mira cuanto debe cada cliente, que pago y que quedo pendiente.
          </p>
        </div>
        {(usersQuery.isLoading || ledgerQuery.isLoading || summaryQuery.isLoading) && (
          <div
            className="flex items-center gap-2 text-xs font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            <Loader2 className="w-4 h-4 animate-spin" />
            Cargando cuentas pendientes...
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

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-6">
        <div className="p-5 rounded-2xl" style={cardStyle}>
          <p
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            Saldo pendiente total
          </p>
          <p className="text-2xl font-black mt-1" style={{ color: colors2000s.text.primary }}>
            {currencyFmt.format(Number(summaryQuery.data?.total_balance ?? 0))}
          </p>
        </div>
        <div className="p-5 rounded-2xl" style={cardStyle}>
          <p
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            Clientes con deuda
          </p>
          <p className="text-2xl font-black mt-1" style={{ color: colors2000s.text.primary }}>
            {summaryQuery.data?.debtors_count ?? 0}
          </p>
        </div>
        <div className="p-5 rounded-2xl" style={cardStyle}>
          <p
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            Saldo promedio
          </p>
          <p className="text-2xl font-black mt-1" style={{ color: colors2000s.orange.accent }}>
            {currencyFmt.format(Number(summaryQuery.data?.average_balance ?? 0))}
          </p>
        </div>
        <div className="p-5 rounded-2xl" style={cardStyle}>
          <p
            className="text-[10px] font-black uppercase tracking-widest"
            style={{ color: colors2000s.text.secondary }}
          >
            Movimientos
          </p>
          <p className="text-2xl font-black mt-1" style={{ color: colors2000s.text.primary }}>
            {summaryQuery.data?.total_movements ?? 0}
          </p>
        </div>
      </div>

      <div className="grid xl:grid-cols-[320px_1fr_320px] gap-6">
        <div className="p-6 rounded-3xl space-y-4" style={cardStyle}>
          <div className="flex items-center gap-3">
            <WalletCards className="w-5 h-5" style={{ color: colors2000s.orange.accent }} />
            <h3
              className="text-lg font-black uppercase tracking-tight"
              style={{ color: colors2000s.text.primary }}
            >
              Cliente
            </h3>
          </div>
          <select
            value={selectedClientId || ''}
            onChange={(e) => setSelectedClientId(e.target.value)}
            className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
            style={inputStyle}
          >
            {clients.map((client) => (
              <option key={client.public_id} value={client.public_id}>
                {client.first_name || client.email} {client.last_name || ''}
              </option>
            ))}
          </select>

          <form
            onSubmit={(event) => {
              void handleSubmit(event)
            }}
            className="space-y-3"
          >
            <select
              value={movementForm.movement_type}
              onChange={(e) =>
                setMovementForm((prev) => ({
                  ...prev,
                  movement_type: e.target.value as typeof prev.movement_type
                }))
              }
              className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
              style={inputStyle}
            >
              <option value="charge">Cargo</option>
              <option value="payment">Pago</option>
              <option value="adjustment">Ajuste</option>
              <option value="refund">Devolucion</option>
            </select>
            <input
              value={movementForm.amount}
              onChange={(e) => setMovementForm((prev) => ({ ...prev, amount: e.target.value }))}
              className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
              style={inputStyle}
              placeholder="Monto"
              required
            />
            <input
              value={movementForm.appointment_id}
              onChange={(e) =>
                setMovementForm((prev) => ({ ...prev, appointment_id: e.target.value }))
              }
              className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
              style={inputStyle}
              placeholder="Turno asociado (opcional)"
            />
            <textarea
              value={movementForm.notes}
              onChange={(e) => setMovementForm((prev) => ({ ...prev, notes: e.target.value }))}
              className="w-full min-h-24 rounded-2xl px-4 py-3 font-bold outline-none resize-y"
              style={inputStyle}
              placeholder="Notas"
            />
            <button
              type="submit"
              disabled={!selectedClientId || addMovement.isPending}
              className="w-full px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest disabled:opacity-50"
              style={buttonStyles2000s.selected}
            >
              Guardar movimiento
            </button>
          </form>
        </div>

        <div className="p-6 rounded-3xl space-y-5" style={cardStyle}>
          <div className="flex items-center justify-between">
            <div>
              <h3
                className="text-lg font-black uppercase tracking-tight"
                style={{ color: colors2000s.text.primary }}
              >
                Estado de cuenta
              </h3>
              <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
                Cliente seleccionado:{' '}
                {clients.find((client) => client.public_id === selectedClientId)?.email || '-'}
              </p>
            </div>
            <div className="text-right">
              <p
                className="text-[10px] font-black uppercase tracking-widest"
                style={{ color: colors2000s.text.secondary }}
              >
                Saldo actual
              </p>
              <p className="text-3xl font-black" style={{ color: colors2000s.orange.accent }}>
                {currencyFmt.format(Number(ledgerQuery.data?.balance ?? 0))}
              </p>
            </div>
          </div>

          <div className="space-y-3">
            {ledgerQuery.data?.movements.map((movement) => (
              <div
                key={movement.public_id}
                className="rounded-2xl p-4 bg-white flex flex-col md:flex-row md:items-center md:justify-between gap-3"
                style={create2000sListCardStyle()}
              >
                <div>
                  <p
                    className="text-sm font-black uppercase"
                    style={{ color: colors2000s.text.primary }}
                  >
                    {movementTypeLabels[movement.movement_type]}
                  </p>
                  <p
                    className="text-[11px] font-bold"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    {new Date(movement.created_at).toLocaleString('es-AR')}
                    {movement.notes ? ` · ${movement.notes}` : ''}
                  </p>
                </div>
                <div className="text-right">
                  <p className="text-sm font-black" style={{ color: colors2000s.orange.accent }}>
                    {currencyFmt.format(Number(movement.amount))}
                  </p>
                  <p
                    className="text-[11px] font-bold"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    Saldo: {currencyFmt.format(Number(movement.balance_after))}
                  </p>
                </div>
              </div>
            ))}
            {!ledgerQuery.data?.movements.length && !ledgerQuery.isLoading && (
              <div
              className="rounded-2xl p-6 bg-white text-sm font-bold"
              style={{ ...create2000sListCardStyle(), color: colors2000s.text.secondary }}
              >
                Este cliente todavia no tiene movimientos registrados.
              </div>
            )}
          </div>
        </div>

        <div className="p-6 rounded-3xl space-y-4" style={cardStyle}>
          <div>
            <h3
              className="text-lg font-black uppercase tracking-tight"
              style={{ color: colors2000s.text.primary }}
            >
              Clientes con mayor deuda
            </h3>
            <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
              Clientes con mayor saldo pendiente.
            </p>
          </div>
          <div className="space-y-3">
            {(summaryQuery.data?.top_debtors || []).map((debtor) => (
              <div
                key={debtor.client_id}
                className="rounded-2xl p-4 bg-white"
                style={create2000sListCardStyle()}
              >
                <p className="text-sm font-black" style={{ color: colors2000s.text.primary }}>
                  {debtor.client_name}
                </p>
                <p
                  className="text-[11px] font-bold mt-1"
                  style={{ color: colors2000s.text.secondary }}
                >
                  Ultimo movimiento: {new Date(debtor.last_movement_at).toLocaleDateString('es-AR')}
                </p>
                <p className="text-sm font-black mt-2" style={{ color: colors2000s.orange.accent }}>
                  {currencyFmt.format(Number(debtor.balance))}
                </p>
              </div>
            ))}
            {(summaryQuery.data?.top_debtors.length ?? 0) === 0 && !summaryQuery.isLoading && (
              <div
              className="rounded-2xl p-4 bg-white text-sm font-bold"
              style={{ ...create2000sListCardStyle(), color: colors2000s.text.secondary }}
              >
                No hay clientes con deuda registrada.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

export default LedgerPage
