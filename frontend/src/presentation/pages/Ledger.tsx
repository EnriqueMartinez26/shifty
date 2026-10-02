import React, { useState } from 'react'

import { WalletCards } from 'lucide-react'

import type { LedgerClient } from '@application/services/LedgerService'

import { getErrorMessage } from '@shared/errors/getErrorMessage'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { FormFeedback, type FormFeedbackMessage } from '../components/molecules/FormFeedback'
import { PageHeader } from '../components/molecules/PageHeader'
import { QueryErrorNotice } from '../components/molecules/QueryErrorNotice'
import { useConfirm } from '../hooks/useConfirm'
import {
  useAddLedgerMovement,
  useCustomerLedger,
  useLedgerClients,
  useLedgerSummary
} from '../hooks/useLedger'
import { useStoreWriteAccess } from '../hooks/useStoreWriteAccess'
import {
  currencyFmtEsAr as currencyFmt,
  formatDateEsAr,
  formatDateTimeEsAr
} from '../lib/formatters'
import {
  create2000sInputStyle,
  create2000sListCardStyle,
  create2000sPanelStyle
} from '../lib/surfaceStyles'

type MovementType = 'charge' | 'payment' | 'adjustment' | 'refund'

const movementTypeLabels: Record<MovementType, string> = {
  charge: 'Cargo',
  payment: 'Pago',
  adjustment: 'Ajuste',
  refund: 'Devolucion'
}

// Mismo tope que LedgerMovementCreate.amount en el backend (ge=0,
// le=10_000_000, decimal_places=2). Un movimiento en 0 no mueve el saldo: se
// pide mayor a 0.
const MAX_AMOUNT = 10_000_000
const AMOUNT_MESSAGE = 'Ingresá un monto mayor a $ 0 y hasta $ 10.000.000, con hasta 2 decimales.'

/** Monto tipeado -> numero valido para el backend, o null. Acepta coma decimal. */
const parseAmount = (raw: string): number | null => {
  const normalized = raw.trim().replace(',', '.')
  if (!/^\d+(\.\d{1,2})?$/.test(normalized)) return null
  const amount = Number(normalized)
  return amount > 0 && amount <= MAX_AMOUNT ? amount : null
}

// Un 422 de Pydantic nombra el campo; el texto crudo nunca llega (regla 20).
const MOVEMENT_FIELD_MESSAGES: Partial<Record<string, string>> = {
  amount: AMOUNT_MESSAGE,
  movement_type: 'Elegí el tipo de movimiento.',
  appointment_id: 'El turno asociado no es válido. Revisá el código o dejalo vacío.',
  notes: 'Las notas pueden tener hasta 500 caracteres.'
}

const inputStyle = create2000sInputStyle()
const cardStyle = create2000sPanelStyle()

const LedgerPage: React.FC = () => {
  // /ledger/clients y no /users/: este sirve tambien al profesional (403 en
  // /users/) y solo trae clientes, filtrados en el backend (FF-20).
  // La busqueda viaja al enviarla (Enter o "Buscar"), no por tecla.
  const [clientSearch, setClientSearch] = useState('')
  const [submittedSearch, setSubmittedSearch] = useState('')
  const clientsQuery = useLedgerClients(submittedSearch)
  const summaryQuery = useLedgerSummary()
  const addMovement = useAddLedgerMovement()
  // Tienda suspendida (FF-15): POST /ledger/customers/{id}/movements no esta en
  // SUSPENSION_ALLOWED_WRITES y responde 402.
  const writeAccess = useStoreWriteAccess()
  const clients = clientsQuery.data ?? []
  // Una eleccion explicita se guarda entera y se sostiene aunque la busqueda
  // ya no la traiga: caer al primero de otra busqueda mandaba el movimiento
  // a otro cliente. Sin eleccion se usa el primero, derivado (regla 27).
  const [pickedClient, setPickedClient] = useState<LedgerClient | null>(null)
  const selectedClient = pickedClient ?? clients[0]
  const clientOptions =
    selectedClient && !clients.some((c) => c.public_id === selectedClient.public_id)
      ? [selectedClient, ...clients]
      : clients
  const effectiveClientId = selectedClient?.public_id ?? null
  const ledgerQuery = useCustomerLedger(effectiveClientId)
  // El tipo arranca SIN elegir y vuelve a "sin elegir" despues de guardar:
  // volver solo a "Cargo" hizo que un pago se cargara como deuda (QA
  // 2026-10-02). Recordar el ultimo tipo tiene el mismo riesgo con el
  // movimiento siguiente; elegirlo cada vez, mas la confirmacion, no.
  const emptyMovementForm = {
    movement_type: '' as MovementType | '',
    amount: '',
    appointment_id: '',
    notes: ''
  }
  const [movementForm, setMovementForm] = useState(emptyMovementForm)
  const [feedback, setFeedback] = useState<FormFeedbackMessage | null>(null)
  const { confirm, confirmDialog } = useConfirm()
  const showError = (text: string) => setFeedback({ tone: 'error', text })

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!effectiveClientId) return
    const movementType = movementForm.movement_type
    if (!movementType) {
      showError('Elegí el tipo de movimiento.')
      return
    }
    const amount = parseAmount(movementForm.amount)
    if (amount === null) {
      showError(AMOUNT_MESSAGE)
      return
    }
    setFeedback(null)
    const clientName = selectedClient?.name ?? 'el cliente'
    const confirmed = await confirm(
      `¿Registrar ${movementTypeLabels[movementType]} de ${currencyFmt.format(amount)} a ${clientName}?`,
      { confirmLabel: 'Registrar', cancelLabel: 'Volver' }
    )
    if (!confirmed) return
    try {
      await addMovement.mutateAsync({
        clientId: effectiveClientId,
        payload: {
          movement_type: movementType,
          amount,
          appointment_id: movementForm.appointment_id || undefined,
          notes: movementForm.notes || undefined
        }
      })
      setMovementForm(emptyMovementForm)
      setFeedback({ tone: 'success', text: 'Movimiento registrado' })
    } catch (error: unknown) {
      showError(
        getErrorMessage(error, 'No se pudo registrar el movimiento', {}, MOVEMENT_FIELD_MESSAGES)
      )
    }
  }

  return (
    <div className="space-y-8 duration-500">
      <PageHeader
        title="Cuentas pendientes"
        description="Mira cuanto debe cada cliente, que pago y que quedo pendiente."
        isLoading={clientsQuery.isLoading || ledgerQuery.isLoading || summaryQuery.isLoading}
        loadingText="Cargando cuentas pendientes..."
      />

      <QueryErrorNotice
        error={clientsQuery.error ?? summaryQuery.error ?? ledgerQuery.error}
        message="No se pudieron cargar las cuentas pendientes."
      />

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
          <form
            onSubmit={(e) => {
              e.preventDefault()
              setSubmittedSearch(clientSearch)
              // Sin eleccion explicita el cliente activo puede cambiar.
              if (!pickedClient) setMovementForm(emptyMovementForm)
            }}
            className="flex gap-2"
          >
            <input
              value={clientSearch}
              onChange={(e) => setClientSearch(e.target.value)}
              maxLength={80}
              aria-label="Buscar cliente"
              className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
              style={inputStyle}
              placeholder="Buscar por nombre o telefono"
            />
            <button
              type="submit"
              className="px-4 rounded-2xl text-xs font-black uppercase"
              style={buttonStyles2000s.default}
            >
              Buscar
            </button>
          </form>
          <select
            value={effectiveClientId ?? ''}
            onChange={(e) => {
              setPickedClient(clientOptions.find((c) => c.public_id === e.target.value) ?? null)
              setMovementForm(emptyMovementForm)
              setFeedback(null)
            }}
            className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
            style={inputStyle}
          >
            {clientOptions.map((client) => (
              <option key={client.public_id} value={client.public_id}>
                {client.name}
              </option>
            ))}
          </select>

          <form
            noValidate
            onSubmit={(event) => {
              void handleSubmit(event)
            }}
            className="space-y-3"
          >
            <select
              aria-label="Tipo de movimiento"
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
              <option value="" disabled>
                Elegí el tipo de movimiento
              </option>
              <option value="charge">Cargo</option>
              <option value="payment">Pago</option>
              <option value="adjustment">Ajuste</option>
              <option value="refund">Devolucion</option>
            </select>
            <input
              aria-label="Monto"
              inputMode="decimal"
              value={movementForm.amount}
              onChange={(e) => setMovementForm((prev) => ({ ...prev, amount: e.target.value }))}
              className="w-full rounded-2xl px-4 py-3 font-bold outline-none"
              style={inputStyle}
              placeholder="Monto"
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
              disabled={!effectiveClientId || addMovement.isPending || writeAccess.readOnly}
              title={writeAccess.readOnly ? writeAccess.reason : undefined}
              className="w-full px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest disabled:opacity-50"
              style={buttonStyles2000s.selected}
            >
              Guardar movimiento
            </button>
            <FormFeedback feedback={feedback} />
          </form>
          {confirmDialog}
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
                Cliente seleccionado: {selectedClient?.email ?? selectedClient?.name ?? '-'}
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
                {currencyFmt.format(Number(ledgerQuery.balance ?? 0))}
              </p>
            </div>
          </div>

          <div className="space-y-3">
            {ledgerQuery.movements.map((movement) => (
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
                    {formatDateTimeEsAr(movement.created_at)}
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
            {!ledgerQuery.movements.length && !ledgerQuery.isLoading && (
              <div
                className="rounded-2xl p-6 bg-white text-sm font-bold"
                style={{ ...create2000sListCardStyle(), color: colors2000s.text.secondary }}
              >
                Este cliente todavia no tiene movimientos registrados.
              </div>
            )}
            {ledgerQuery.movements.length > 0 && (
              <p className="text-xs font-bold" style={{ color: colors2000s.text.secondary }}>
                Mostrando {ledgerQuery.movements.length} de {ledgerQuery.total}
              </p>
            )}
            {ledgerQuery.hasNextPage && (
              <button
                type="button"
                onClick={() => {
                  void ledgerQuery.fetchNextPage()
                }}
                disabled={ledgerQuery.isFetchingNextPage}
                className="w-full px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest disabled:opacity-50"
                style={buttonStyles2000s.default}
              >
                {ledgerQuery.isFetchingNextPage ? 'Cargando...' : 'Ver mas'}
              </button>
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
                  Ultimo movimiento: {formatDateEsAr(debtor.last_movement_at)}
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
