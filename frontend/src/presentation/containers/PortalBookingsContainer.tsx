import React, { useState } from 'react'

import type {
  BulkCancelSkipped,
  PortalBookingsWindowHours,
  RecentPortalBooking
} from '@application/services/PortalBookingsService'

import { getErrorMessage } from '@shared/errors/getErrorMessage'

import { BulkCancelConfirm } from '../components/molecules/BulkCancelConfirm'
import { BulkCancelResultNotice } from '../components/molecules/BulkCancelResultNotice'
import { FormErrorAlert } from '../components/molecules/FormErrorAlert'
import { PageHeader } from '../components/molecules/PageHeader'
import { PortalBookingsToolbar } from '../components/molecules/PortalBookingsToolbar'
import { PortalBookingsList } from '../components/organisms/PortalBookingsList'
import { useAuth } from '../context/AuthContext'
import { ROLES_ADMIN_SUPER, hasAnyRole } from '../context/roles'
import { useBulkCancelPortalBookings, useRecentPortalBookings } from '../hooks/usePortalBookings'
import { useStoreWriteAccess } from '../hooks/useStoreWriteAccess'

const DEFAULT_HOURS: PortalBookingsWindowHours = 72

const EMPTY: RecentPortalBooking[] = []

interface CancelOutcome {
  cancelledCount: number
  skipped: BulkCancelSkipped[]
  labels: Record<string, string>
}

/**
 * Limpieza de reservas del portal (S6, antiabuso): el dueno ve lo que entro
 * por la pagina publica en las ultimas horas y cancela de una vez lo que
 * parece abuso. Solo el dueno o administrador, igual que el backend.
 */
export const PortalBookingsContainer: React.FC = () => {
  const { user } = useAuth()
  const canManage = hasAnyRole(user?.role, ROLES_ADMIN_SUPER, user?.is_global_admin)
  // Tienda suspendida: POST /appointments/bulk-cancel no esta en
  // SUSPENSION_ALLOWED_WRITES y responde 402.
  const writeAccess = useStoreWriteAccess()
  const readOnlyReason = writeAccess.readOnly ? writeAccess.reason : undefined

  const [hours, setHours] = useState<PortalBookingsWindowHours>(DEFAULT_HOURS)
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(new Set())
  const [isConfirming, setIsConfirming] = useState(false)
  const [reason, setReason] = useState('')
  const [outcome, setOutcome] = useState<CancelOutcome | null>(null)
  const [errorMessage, setErrorMessage] = useState('')

  const recent = useRecentPortalBookings(hours, canManage)
  const bulkCancel = useBulkCancelPortalBookings()

  const bookings = recent.data ?? EMPTY
  // Solo cuenta lo elegido que sigue en la lista: si la lista se refresco sin
  // un turno, no queda seleccionado a escondidas.
  const selectedBookings = bookings.filter((booking) => selectedIds.has(booking.public_id))
  const visibleSelection = new Set(selectedBookings.map((booking) => booking.public_id))

  if (!canManage) {
    return (
      <PageHeader
        title="Reservas recientes del portal"
        description="Solo el dueño o un administrador de la tienda puede revisar y cancelar estas reservas."
        isLoading={false}
        loadingText=""
      />
    )
  }

  const changeHours = (next: PortalBookingsWindowHours) => {
    setHours(next)
    setSelectedIds(new Set())
    setIsConfirming(false)
  }

  const toggle = (id: string) => {
    const next = new Set(visibleSelection)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    setSelectedIds(next)
  }

  const toggleAll = () => {
    const allSelected = selectedBookings.length === bookings.length
    setSelectedIds(allSelected ? new Set() : new Set(bookings.map((b) => b.public_id)))
  }

  const startCancel = () => {
    setOutcome(null)
    setErrorMessage('')
    setIsConfirming(true)
  }

  const confirmCancel = async () => {
    const labels = Object.fromEntries(selectedBookings.map((b) => [b.public_id, b.client_name]))
    setErrorMessage('')
    try {
      const result = await bulkCancel.mutateAsync({
        ids: selectedBookings.map((booking) => booking.public_id),
        reason
      })
      setOutcome({ cancelledCount: result.cancelled.length, skipped: result.skipped, labels })
      setSelectedIds(new Set())
      setReason('')
      setIsConfirming(false)
    } catch (error: unknown) {
      setErrorMessage(
        getErrorMessage(error, 'No se pudieron cancelar las reservas. Probá de nuevo.')
      )
    }
  }

  return (
    <div className="space-y-6 duration-700">
      <PageHeader
        title="Reservas recientes del portal"
        description="Turnos futuros que se reservaron desde tu página pública. Si ves reservas sospechosas, seleccionalas y cancelalas juntas."
        isLoading={recent.isFetching === true && !recent.isLoading}
        loadingText="Actualizando"
      />
      <PortalBookingsToolbar
        hours={hours}
        onHoursChange={changeHours}
        selectedCount={selectedBookings.length}
        onCancelSelected={startCancel}
        readOnlyReason={readOnlyReason}
      />
      {isConfirming && selectedBookings.length > 0 && (
        <BulkCancelConfirm
          count={selectedBookings.length}
          reason={reason}
          onReasonChange={setReason}
          onConfirm={() => void confirmCancel()}
          onBack={() => setIsConfirming(false)}
          isPending={bulkCancel.isPending}
        />
      )}
      <FormErrorAlert message={errorMessage} />
      {outcome && (
        <BulkCancelResultNotice
          cancelledCount={outcome.cancelledCount}
          skipped={outcome.skipped}
          labels={outcome.labels}
        />
      )}
      <PortalBookingsList
        bookings={bookings}
        isLoading={recent.isLoading}
        error={recent.error}
        selectedIds={visibleSelection}
        onToggle={toggle}
        onToggleAll={toggleAll}
      />
    </div>
  )
}
