import React, { useMemo, useState } from 'react'

import {
  addDays,
  endOfMonth,
  endOfWeek,
  format,
  startOfDay,
  startOfMonth,
  startOfWeek,
  subDays
} from 'date-fns'

import { getErrorMessage, isStateConflictError } from '@shared/errors/getErrorMessage'
import { formatArgentinaDate, formatArgentinaTime } from '@shared/utils/argentinaTime'
import { buildRebookUrl } from '@shared/utils/clientWhatsApp'

import { BlocksPanel, type EditableBlock } from './BlocksPanel'
import {
  RescheduleAppointmentDialog,
  type ReschedulableAppointment
} from './RescheduleAppointmentDialog'
import {
  AppointmentActions,
  type AppointmentAction
} from '../components/molecules/AppointmentActions'
import { ClientWhatsAppButton } from '../components/molecules/ClientWhatsAppButton'
import { QueryErrorNotice } from '../components/molecules/QueryErrorNotice'
import { AbsencesTimeline } from '../components/organisms/calendar/AbsencesTimeline'
import { AgendaDayView } from '../components/organisms/calendar/AgendaDayView'
import { AgendaEventPill } from '../components/organisms/calendar/AgendaEventPill'
import { AgendaListView } from '../components/organisms/calendar/AgendaListView'
import { AgendaRangeGrid } from '../components/organisms/calendar/AgendaRangeGrid'
import { AgendaToolbar, type CalendarView } from '../components/organisms/calendar/AgendaToolbar'
import { NewAppointmentModal } from '../components/organisms/NewAppointmentModal'
import { useAuth } from '../context/AuthContext'
import {
  ROLE_PROFESSIONAL,
  ROLE_RECEPTIONIST,
  ROLE_STORE_ADMIN,
  ROLE_SUPER_ADMIN,
  canonicalRole,
  hasAnyRole
} from '../context/roles'
import { useAppointmentBlocks, useDeleteAppointmentBlock } from '../hooks/useAppointmentBlocks'
import {
  useCalendarAgenda,
  useCancelAppointment,
  useCompleteAppointment,
  useConfirmAppointment,
  useMarkAbsentAppointment,
  useReleaseAppointment
} from '../hooks/useCalendarAgenda'
import { useConfirm } from '../hooks/useConfirm'
import { useManagedStaff } from '../hooks/useManagedStaff'
import { useStoreSettings } from '../hooks/useStores'
import { useStoreWriteAccess } from '../hooks/useStoreWriteAccess'
import {
  NO_EVENTS,
  buildUnifiedEvents,
  groupEventsByDay,
  toInstantIso,
  type UnifiedCalendarEvent
} from '../lib/calendarEvents'
import {
  MIN_APPOINTMENT_MINUTES,
  buildDayGrid,
  gridPlacement,
  rangeFromInstants
} from '../lib/calendarGrid'
import { mondayBasedWeekday, storeRangesFor, workingRangesFor } from '../lib/staffHours'

export const CalendarContainer: React.FC = () => {
  const { confirm, confirmDialog } = useConfirm()
  const { user } = useAuth()
  // Roles canonicos (legacy 'admin'/'staff' incluidos), como el backend (FF-14).
  const canReleaseAppointments = hasAnyRole(
    user?.role,
    [ROLE_STORE_ADMIN, ROLE_SUPER_ADMIN],
    user?.is_global_admin
  )
  // Confirmar, completar y ausente: admin o personal (mismo criterio que la API).
  const canManageAppointments =
    canReleaseAppointments || canonicalRole(user?.role) === ROLE_PROFESSIONAL
  // Bloqueos: admin y profesional (este, para cualquier profesional,
  // D-20260929-08); recepcion los ve sin gestionarlos (D-20260929-09).
  // Cancelar turnos en bloque es solo de administradores (FF-34).
  const canManageBlocks = canManageAppointments
  const canCancelAffected = canReleaseAppointments
  // Cancelar o reprogramar (D-20260929-03): administracion y recepcion,
  // cualquier turno; el profesional, solo los de su agenda (su ficha comparte
  // id con su usuario). Es solo lo que se ofrece: la guarda es el backend (403).
  const currentRole = canonicalRole(user?.role, user?.is_global_admin)
  const cancelsAnyAppointment = canReleaseAppointments || currentRole === ROLE_RECEPTIONIST
  const canCancelOrRescheduleOf = (staffId: string) =>
    cancelsAnyAppointment ||
    (currentRole === ROLE_PROFESSIONAL && Boolean(user?.public_id) && staffId === user?.public_id)
  // Tienda suspendida (FF-15): se deshabilita lo que el backend responde con
  // 402; cancelar y liberar siguen (D-20260930-12).
  const writeAccess = useStoreWriteAccess()
  const readOnlyReason = writeAccess.readOnly ? writeAccess.reason : null
  const [selectedDate, setSelectedDate] = useState(new Date())
  const [view, setView] = useState<CalendarView>('day')
  const [message, setMessage] = useState('')
  const [isNewAppointmentOpen, setIsNewAppointmentOpen] = useState(false)
  // El panel de bloqueos se remonta con `key` al elegir otro bloqueo: sin
  // efecto que copie el bloqueo al formulario (regla 27).
  const [blockToEdit, setBlockToEdit] = useState<EditableBlock | null>(null)
  const [rescheduleTarget, setRescheduleTarget] = useState<ReschedulableAppointment | null>(null)

  const rangeStart = useMemo(() => {
    if (view === 'day' || view === 'list') return selectedDate
    if (view === 'week') return startOfWeek(selectedDate, { weekStartsOn: 1 })
    return startOfMonth(selectedDate)
  }, [selectedDate, view])

  const rangeEnd = useMemo(() => {
    if (view === 'day') return selectedDate
    if (view === 'list') return addDays(selectedDate, 13)
    if (view === 'week') return endOfWeek(selectedDate, { weekStartsOn: 1 })
    return endOfMonth(selectedDate)
  }, [selectedDate, view])

  const rangeKeyFrom = format(rangeStart, 'yyyy-MM-dd')
  const rangeKeyTo = format(rangeEnd, 'yyyy-MM-dd')
  const dateStr = format(selectedDate, 'yyyy-MM-dd')

  const { data: staffMembers, isLoading: loadingStaff, error: staffError } = useManagedStaff()
  // Nombre y slug de la tienda para el texto de WhatsApp y el deep-link.
  const { data: storeSettings } = useStoreSettings()
  const agendaQuery = useCalendarAgenda(rangeKeyFrom, rangeKeyTo)
  // La agenda trae hasta un tope de paginas; si el servidor tiene mas turnos
  // en el rango, se avisa en vez de mostrar la lista como completa (F10-12).
  const agendaRange = agendaQuery.data
  const truncatedAgenda =
    agendaRange && agendaRange.total > agendaRange.appointments.length
      ? { shown: agendaRange.appointments.length, total: agendaRange.total }
      : null
  const blocksQuery = useAppointmentBlocks(rangeKeyFrom, rangeKeyTo)
  const deleteBlock = useDeleteAppointmentBlock()
  const releaseAppointment = useReleaseAppointment()
  /** Huecos de la jornada partida que el dueno decidio ver a escala real. */
  const [expandedGaps, setExpandedGaps] = useState<ReadonlySet<string>>(() => new Set())

  const toggleGap = (key: string) =>
    setExpandedGaps((prev) => {
      const next = new Set(prev)
      if (!next.delete(key)) next.add(key)
      return next
    })
  const confirmAppointment = useConfirmAppointment()
  const completeAppointment = useCompleteAppointment()
  const markAbsentAppointment = useMarkAbsentAppointment()
  const cancelAppointment = useCancelAppointment()
  const transitionBusy =
    releaseAppointment.isPending ||
    cancelAppointment.isPending ||
    confirmAppointment.isPending ||
    completeAppointment.isPending ||
    markAbsentAppointment.isPending

  const blocksInRange = useMemo(() => {
    // El servidor ya manda solo los activos del rango (F4-07); el filtro de
    // is_active queda por si llega uno igual (FF-12).
    return (blocksQuery.data || []).filter((block) => {
      if (!block.is_active) return false
      const startsAt = new Date(block.starts_at)
      return startsAt >= startOfDay(rangeStart) && startsAt <= addDays(startOfDay(rangeEnd), 1)
    })
  }, [blocksQuery.data, rangeEnd, rangeStart])

  const blocksForSelectedDate = useMemo(() => {
    // `starts_at` es UTC: recortar sus 10 primeros caracteres daba el dia UTC,
    // asi que un bloqueo de 21:00 o mas tarde desaparecia del dia elegido.
    return blocksInRange.filter((block) => formatArgentinaDate(block.starts_at) === dateStr)
  }, [blocksInRange, dateStr])

  const unifiedEvents = useMemo<UnifiedCalendarEvent[]>(
    () =>
      buildUnifiedEvents({
        appointments: agendaQuery.data?.appointments ?? [],
        blocks: blocksInRange,
        staffMembers
      }),
    [agendaQuery.data, blocksInRange, staffMembers]
  )

  const eventsByDay = useMemo(() => groupEventsByDay(unifiedEvents), [unifiedEvents])

  const eventsForSelectedDate = eventsByDay.get(dateStr) ?? NO_EVENTS

  // Horario efectivo de cada profesional el dia elegido (FF-03): el suyo o,
  // sin ninguna franja cargada, el del local (D-20260929-01). `null` = todavia
  // no se sabe (la ficha del local no cargo): no se pinta nada.
  const weekday = mondayBasedWeekday(selectedDate)
  const hoursOfDay = useMemo(() => {
    const storeRanges = storeRangesFor(storeSettings?.business_hours, weekday)
    const byStaff = new Map(
      (staffMembers ?? []).map((staff) => [
        staff.id,
        workingRangesFor(staff.schedules, weekday, storeRanges)
      ])
    )
    return { storeRanges, byStaff }
  }, [staffMembers, storeSettings?.business_hours, weekday])

  /**
   * El rango visible es la union de los horarios de atencion (del local y de
   * cada profesional) y los eventos del dia. Acotar la grilla solo con los
   * horarios volveria a esconder lo que queda afuera: un turno movido a mano,
   * uno heredado de un horario viejo, un bloqueo cargado fuera de hora.
   */
  const dayGrid = useMemo(() => {
    const openRanges = [
      ...(hoursOfDay.storeRanges ?? []),
      ...[...hoursOfDay.byStaff.values()].flatMap((ranges) => ranges ?? [])
    ]

    const eventRanges = eventsForSelectedDate.flatMap((event) => {
      const eventRange = rangeFromInstants(toInstantIso(event.startsAt), toInstantIso(event.endsAt))
      return eventRange ? [eventRange] : []
    })

    return buildDayGrid([...openRanges, ...eventRanges], expandedGaps)
  }, [eventsForSelectedDate, expandedGaps, hoursOfDay])

  const appointmentCards = useMemo(() => {
    return eventsForSelectedDate
      .filter((event) => event.type !== 'block')
      .flatMap((event) => {
        const startIso = toInstantIso(event.startsAt)
        const placement = gridPlacement(
          dayGrid,
          startIso,
          toInstantIso(event.endsAt),
          MIN_APPOINTMENT_MINUTES
        )
        // Un turno sin instante legible no se dibuja: ubicarlo igual lo apila
        // sobre uno real. Queda reportado desde `gridPlacement`.
        if (!placement) return []
        return [{ ...event, ...placement, timeLabel: formatArgentinaTime(startIso) }]
      })
  }, [dayGrid, eventsForSelectedDate])

  const timelineEvents = useMemo(() => {
    return unifiedEvents.filter((event) => event.type === 'block' || event.type === 'absence')
  }, [unifiedEvents])

  const daysInRange = useMemo(() => {
    const days: Date[] = []
    let cursor = startOfDay(rangeStart)
    while (cursor <= rangeEnd) {
      days.push(cursor)
      cursor = addDays(cursor, 1)
    }
    return days
  }, [rangeEnd, rangeStart])

  const handleReleaseAppointment = async (event: UnifiedCalendarEvent) => {
    if (event.type === 'block') return
    const confirmed = await confirm(
      `¿Liberar el turno de ${event.title}? El enlace de pago pendiente también será vencido.`
    )
    if (!confirmed) return
    try {
      await releaseAppointment.mutateAsync(event.id)
      setMessage('Turno liberado correctamente')
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, 'No se pudo liberar el turno'))
      // Un desfasaje de estado significa que la agenda en pantalla quedo vieja:
      // recargarla es parte de la solucion, no algo que el usuario deba deducir.
      if (isStateConflictError(error)) {
        void agendaQuery.refetch()
      }
    }
  }

  const handleCancelAppointment = async (event: UnifiedCalendarEvent) => {
    if (event.type === 'block') return
    // Siempre se confirma; si hay un cobro vivo, se avisa que vence (D-20260929-07).
    const liveChargeWarning =
      event.status === 'pending_payment'
        ? ' El cobro pendiente se va a vencer y su link de pago deja de servir.'
        : ''
    // "Cancelar"/"Confirmar" en un dialogo que cancela era ambiguo (QA 2026-10-02).
    const confirmed = await confirm(`¿Cancelar el turno de ${event.title}?${liveChargeWarning}`, {
      confirmLabel: 'Cancelar turno',
      cancelLabel: 'Volver'
    })
    if (!confirmed) return
    try {
      await cancelAppointment.mutateAsync(event.id)
      setMessage('Turno cancelado')
    } catch (error: unknown) {
      setMessage(
        getErrorMessage(error, 'No se pudo cancelar el turno', {
          PERMISSION_DENIED: 'Solo podés cancelar los turnos de tu agenda.'
        })
      )
      if (isStateConflictError(error)) {
        void agendaQuery.refetch()
      }
    }
  }

  const handleAppointmentAction = async (
    event: UnifiedCalendarEvent,
    action: AppointmentAction
  ) => {
    if (event.type === 'block') return
    if (action === 'release') {
      await handleReleaseAppointment(event)
      return
    }
    if (action === 'cancel') {
      await handleCancelAppointment(event)
      return
    }
    if (action === 'reschedule') {
      setRescheduleTarget({
        id: event.id,
        clientName: event.title,
        serviceName: event.subtitle,
        staffName: event.staffName,
        startsAt: toInstantIso(event.startsAt)
      })
      return
    }
    const textos: Record<
      Exclude<AppointmentAction, 'release' | 'cancel' | 'reschedule'>,
      [string, string, string]
    > = {
      confirm: ['¿Confirmar el turno de', 'Turno confirmado', 'No se pudo confirmar el turno'],
      complete: [
        '¿Marcar como completado el turno de',
        'Turno completado',
        'No se pudo completar el turno'
      ],
      absent: ['¿Marcar como ausente a', 'Turno marcado como ausente', 'No se pudo marcar el turno']
    }
    const [pregunta, exito, fallo] = textos[action]
    if (!(await confirm(`${pregunta} ${event.title}?`))) return
    const mutation =
      action === 'confirm'
        ? confirmAppointment
        : action === 'complete'
          ? completeAppointment
          : markAbsentAppointment
    try {
      await mutation.mutateAsync(event.id)
      setMessage(exito)
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, fallo))
      if (isStateConflictError(error)) {
        void agendaQuery.refetch()
      }
    }
  }

  const goPrev = () =>
    setSelectedDate((prev) => subDays(prev, view === 'month' ? 30 : view === 'week' ? 7 : 1))
  const goNext = () =>
    setSelectedDate((prev) => addDays(prev, view === 'month' ? 30 : view === 'week' ? 7 : 1))

  const handleDeactivateBlock = (blockId: string) => {
    void (async () => {
      try {
        await deleteBlock.mutateAsync(blockId)
        setMessage('Bloqueo desactivado')
      } catch (error: unknown) {
        setMessage(getErrorMessage(error, 'No se pudo desactivar'))
      }
    })()
  }

  const renderActions = (event: UnifiedCalendarEvent, compact: boolean) => {
    if (event.type !== 'appointment') return null
    return (
      <AppointmentActions
        status={event.status}
        hasStarted={event.startsAt <= new Date()}
        canRelease={canReleaseAppointments}
        canManage={canManageAppointments}
        canCancelOrReschedule={canCancelOrRescheduleOf(event.staffId)}
        busy={transitionBusy}
        readOnlyReason={readOnlyReason}
        compact={compact}
        onAction={(action) => {
          void handleAppointmentAction(event, action)
        }}
      />
    )
  }

  // El boton wa.me manual va en TODAS las vistas: la de dia lo habia perdido
  // (review 2026-09-11, LOW) y era justo la que usa el mostrador.
  const renderClientWhatsApp = (event: UnifiedCalendarEvent, compact: boolean) => {
    if (event.type !== 'appointment' || !event.clientPhone) return null
    return (
      <ClientWhatsAppButton
        phone={event.clientPhone}
        status={event.status}
        compact={compact}
        message={{
          clientName: event.title,
          serviceName: event.subtitle,
          staffName: event.staffName,
          startsAt: event.startsAt,
          storeName: storeSettings?.name ?? '',
          rebookUrl:
            storeSettings?.slug && event.serviceId
              ? buildRebookUrl(
                  window.location.origin,
                  storeSettings.slug,
                  event.serviceId,
                  event.staffId
                )
              : null
        }}
      />
    )
  }

  const renderEventPill = (event: UnifiedCalendarEvent, compact = false) => (
    <AgendaEventPill
      key={`${event.type}-${event.id}`}
      event={event}
      compact={compact}
      actions={
        <>
          {renderActions(event, compact)}
          {renderClientWhatsApp(event, compact)}
        </>
      }
    />
  )

  return (
    <div className="space-y-6 duration-700">
      {confirmDialog}
      <AgendaToolbar
        view={view}
        selectedDate={selectedDate}
        onPrev={goPrev}
        onNext={goNext}
        onViewChange={setView}
        onNewAppointment={() => setIsNewAppointmentOpen(true)}
        readOnlyReason={readOnlyReason}
      />

      <QueryErrorNotice
        error={agendaQuery.error ?? staffError ?? blocksQuery.error}
        message="No se pudo cargar la agenda."
      />

      {truncatedAgenda && (
        <div
          role="status"
          className="p-4 rounded-[6px] text-sm font-bold"
          style={{ background: '#fff7ed', border: '1px solid #fed7aa', color: '#c2410c' }}
        >
          {`Se muestran ${truncatedAgenda.shown} de ${truncatedAgenda.total} turnos de este rango. Pasá a la vista de día o de semana para verlos todos.`}
        </div>
      )}

      {message && (
        <div
          className="p-4 rounded-[6px] text-sm font-bold"
          style={{ background: '#fff7ed', border: '1px solid #fed7aa', color: '#c2410c' }}
        >
          {message}
        </div>
      )}

      {view === 'day' && (
        <AgendaDayView
          staffMembers={staffMembers}
          loading={loadingStaff || agendaQuery.isLoading}
          dayGrid={dayGrid}
          hoursOfDay={hoursOfDay}
          blocks={blocksForSelectedDate}
          cards={appointmentCards}
          // Tocar un bloqueo abre su edicion (PATCH, 402 con la tienda suspendida).
          canManageBlocks={canManageBlocks && readOnlyReason === null}
          onToggleGap={toggleGap}
          onEditBlock={setBlockToEdit}
          renderControls={(event) => (
            <>
              {renderActions(event, true)}
              {renderClientWhatsApp(event, true)}
            </>
          )}
        />
      )}
      {view === 'week' && (
        <AgendaRangeGrid
          days={daysInRange}
          eventsByDay={eventsByDay}
          compact={false}
          renderEvent={renderEventPill}
        />
      )}
      {view === 'month' && (
        <AgendaRangeGrid
          days={daysInRange}
          eventsByDay={eventsByDay}
          compact
          renderEvent={renderEventPill}
        />
      )}
      {view === 'list' && (
        <AgendaListView eventsByDay={eventsByDay} renderEvent={(event) => renderEventPill(event)} />
      )}

      <div className={`grid gap-6 ${canManageBlocks ? 'xl:grid-cols-[1.05fr_0.95fr]' : ''}`}>
        <BlocksPanel
          key={blockToEdit?.public_id ?? 'new'}
          staffMembers={staffMembers}
          dateStr={dateStr}
          canManageBlocks={canManageBlocks}
          canCancelAffected={canCancelAffected}
          editTarget={blockToEdit}
          onDoneEditing={() => setBlockToEdit(null)}
          onMessage={setMessage}
        />

        <AbsencesTimeline
          events={timelineEvents}
          canManageBlocks={canManageBlocks}
          onEdit={setBlockToEdit}
          onDeactivate={handleDeactivateBlock}
          readOnlyReason={readOnlyReason}
        />
      </div>
      {isNewAppointmentOpen && (
        <NewAppointmentModal
          onClose={() => setIsNewAppointmentOpen(false)}
          defaultDate={selectedDate}
          isProfessional={user?.role === ROLE_PROFESSIONAL}
        />
      )}
      {rescheduleTarget && (
        <RescheduleAppointmentDialog
          appointment={rescheduleTarget}
          isAdmin={canReleaseAppointments}
          onClose={() => setRescheduleTarget(null)}
          onDone={(text) => {
            setRescheduleTarget(null)
            setMessage(text)
          }}
          onStateConflict={() => {
            void agendaQuery.refetch()
          }}
        />
      )}
    </div>
  )
}
