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
import {
  Calendar as CalendarIcon,
  ChevronLeft,
  ChevronRight,
  Clock,
  Loader2,
  Plus
} from 'lucide-react'

import { getErrorMessage, isStateConflictError } from '@shared/errors/getErrorMessage'
import {
  formatArgentinaDate,
  formatArgentinaDayMonth,
  formatArgentinaTime
} from '@shared/utils/argentinaTime'
import { buildRebookUrl } from '@shared/utils/clientWhatsApp'

import { BlocksPanel, type EditableBlock } from './BlocksPanel'
import {
  RescheduleAppointmentDialog,
  type ReschedulableAppointment
} from './RescheduleAppointmentDialog'
import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import {
  AppointmentActions,
  type AppointmentAction
} from '../components/molecules/AppointmentActions'
import { ClientWhatsAppButton } from '../components/molecules/ClientWhatsAppButton'
import { QueryErrorNotice } from '../components/molecules/QueryErrorNotice'
import { NewAppointmentModal } from '../components/organisms/NewAppointmentModal'
import { StaffColumn } from '../components/organisms/StaffColumn'
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
import { statusStyle } from '../lib/appointmentStatusStyle'
import {
  buildUnifiedEvents,
  groupEventsByDay,
  toInstantIso,
  type UnifiedCalendarEvent
} from '../lib/calendarEvents'
import {
  MIN_APPOINTMENT_MINUTES,
  SLOT_HEIGHT_PX,
  buildDayGrid,
  gridPlacement,
  rangeFromInstants
} from '../lib/calendarGrid'
import {
  mondayBasedWeekday,
  offHoursSegments,
  storeRangesFor,
  workingRangesFor
} from '../lib/staffHours'
import { create2000sPanelStyle } from '../lib/surfaceStyles'

type CalendarView = 'day' | 'week' | 'month' | 'list'

const VIEW_LABELS: Record<CalendarView, string> = {
  day: 'Dia',
  week: 'Semana',
  month: 'Mes',
  list: 'Lista'
}

const panelStyle = create2000sPanelStyle()

const canvasStyle = {
  background: 'white',
  border: `1px solid ${colors2000s.border.default}`,
  boxShadow: colors2000s.shadows.outerMedium
}

const cardStyle = {
  background: 'white',
  border: `1px solid ${colors2000s.border.light}`,
  boxShadow: colors2000s.shadows.insetDark
}

const fieldStyle = {
  ...cardStyle,
  color: colors2000s.text.primary
}

/** Un dia sin eventos: la misma referencia siempre, para que la grilla no se recalcule. */
const NO_EVENTS: readonly UnifiedCalendarEvent[] = []

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
    if (!(await confirm(`¿Cancelar el turno de ${event.title}?${liveChargeWarning}`))) return
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

  const renderEventPill = (event: UnifiedCalendarEvent, compact = false) => {
    const style =
      event.type === 'block'
        ? {
            accent: '#c2410c',
            background: 'linear-gradient(180deg, #fff7ed 0%, #fed7aa 100%)',
            text: '#9a3412'
          }
        : statusStyle(event.status)
    return (
      <div
        key={`${event.type}-${event.id}`}
        className={`relative rounded-[6px] border ${compact ? 'p-2' : 'p-3'}`}
        style={{
          background: style.background,
          borderColor: style.accent,
          boxShadow: '0 3px 6px rgba(0,0,0,0.05)'
        }}
      >
        <p
          className={`${compact ? 'text-[8px]' : 'text-[9px]'} font-black uppercase tracking-widest`}
          style={{ color: style.text }}
        >
          {event.type === 'block' ? 'Bloqueo' : event.status}
        </p>
        <p
          className={`${compact ? 'text-[11px]' : 'text-xs'} font-black`}
          style={{ color: colors2000s.text.primary }}
        >
          {event.title}
        </p>
        <p className="text-[10px] font-bold" style={{ color: colors2000s.text.secondary }}>
          {formatArgentinaTime(toInstantIso(event.startsAt))} -{' '}
          {formatArgentinaTime(toInstantIso(event.endsAt))} · {event.staffName}
        </p>
        {renderActions(event, compact)}
        {renderClientWhatsApp(event, compact)}
      </div>
    )
  }

  const renderDayView = () => (
    <div className="rounded-[8px] border overflow-hidden relative" style={canvasStyle}>
      {(loadingStaff || agendaQuery.isLoading) && (
        <div className="absolute inset-0 z-50 bg-white/60 backdrop-blur-[2px] flex flex-col items-center justify-center">
          <Loader2 className="w-12 h-12 animate-spin text-orange-500 mb-4" />
          <p className="text-xs font-black text-gray-400 uppercase tracking-widest">
            Actualizando agenda...
          </p>
        </div>
      )}

      <div className="overflow-x-auto">
        <div className="min-w-[800px]">
          <div className="flex border-b" style={{ borderColor: colors2000s.border.light }}>
            <div
              className="w-20 flex-shrink-0 flex items-center justify-center border-r"
              style={{ borderColor: colors2000s.border.light }}
            >
              <Clock size={16} className="text-gray-400" />
            </div>
            <div className="flex flex-1" style={panelStyle}>
              {staffMembers?.map((staff, idx) => (
                <div
                  key={staff.id}
                  className="flex-1 min-w-[150px] p-4 text-center border-r"
                  style={{ borderColor: colors2000s.border.light }}
                >
                  <div
                    className="w-10 h-10 rounded-full text-white flex items-center justify-center mx-auto mb-2 font-black text-xs shadow-md"
                    style={{
                      background:
                        idx % 2 === 0
                          ? 'linear-gradient(180deg, #3b82f6 0%, #2563eb 100%)'
                          : `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
                      boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
                    }}
                  >
                    {staff.displayName
                      .split(' ')
                      .map((word) => word[0])
                      .join('')
                      .toUpperCase()}
                  </div>
                  <p className="text-[10px] font-black uppercase tracking-tight text-gray-800">
                    {staff.displayName}
                  </p>
                </div>
              ))}
            </div>
          </div>

          <div className="h-[600px] overflow-y-auto relative bg-white">
            <div className="flex">
              <div
                className="w-20 flex-shrink-0 bg-white sticky left-0 z-10 border-r"
                style={{ borderColor: colors2000s.border.light }}
              >
                <div className="relative" style={{ height: dayGrid.totalHeightPx }}>
                  {dayGrid.bands.map((band) =>
                    band.kind === 'open' ? (
                      band.labels.map((label) => (
                        <div
                          key={label.text}
                          className="absolute inset-x-0 border-b border-gray-50 flex items-start justify-center pt-2"
                          style={{ top: label.topPx, height: SLOT_HEIGHT_PX }}
                        >
                          <span className="text-[10px] font-black text-gray-400">{label.text}</span>
                        </div>
                      ))
                    ) : (
                      <button
                        key={band.key}
                        type="button"
                        onClick={() => toggleGap(band.key)}
                        title={`Cerrado ${band.label}`}
                        aria-expanded={band.expanded}
                        className="absolute inset-x-0 border-y border-dashed flex items-center justify-center gap-1 text-[9px] font-black uppercase tracking-widest"
                        style={{
                          top: band.topPx,
                          height: band.heightPx,
                          background: colors2000s.bg.disabled,
                          borderColor: colors2000s.border.default,
                          color: colors2000s.text.secondary
                        }}
                      >
                        {band.expanded ? '▾' : '▸'} Cerrado
                      </button>
                    )
                  )}
                </div>
              </div>

              <div className="flex flex-1">
                {staffMembers?.map((staff) => {
                  const working = hoursOfDay.byStaff.get(staff.id) ?? null
                  return (
                    <StaffColumn
                      key={staff.id}
                      grid={dayGrid}
                      offHours={working ? offHoursSegments(dayGrid, working) : []}
                      blocks={blocksForSelectedDate.filter((block) => block.staff_id === staff.id)}
                      cards={appointmentCards
                        .filter((event) => event.staffId === staff.id)
                        .map((event) => ({
                          id: event.id,
                          title: event.title,
                          subtitle: event.subtitle,
                          status: event.status,
                          top: event.top,
                          height: event.height,
                          timeLabel: event.timeLabel,
                          controls: (
                            <>
                              {renderActions(event, true)}
                              {renderClientWhatsApp(event, true)}
                            </>
                          )
                        }))}
                      canManageBlocks={canManageBlocks}
                      onEditBlock={setBlockToEdit}
                    />
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )

  const renderRangeGrid = (compact = false) => (
    <div className={compact ? 'overflow-x-auto' : undefined}>
      <div
        className={`grid ${compact ? 'grid-cols-7 min-w-[900px]' : 'grid-cols-1 md:grid-cols-2 xl:grid-cols-4'} gap-4`}
      >
        {daysInRange.map((day) => {
          const dayEvents = eventsByDay.get(format(day, 'yyyy-MM-dd')) ?? NO_EVENTS
          return (
            <div key={day.toISOString()} className="rounded-[6px] p-4 bg-white" style={cardStyle}>
              <div className="mb-3">
                <p
                  className="text-[9px] font-black uppercase tracking-widest"
                  style={{ color: colors2000s.orange.accent }}
                >
                  {format(day, 'EEE')}
                </p>
                <p className="text-lg font-black" style={{ color: colors2000s.text.primary }}>
                  {format(day, 'dd/MM')}
                </p>
              </div>
              <div className="space-y-2 max-h-64 overflow-auto">
                {dayEvents
                  .slice(0, compact ? 4 : dayEvents.length)
                  .map((event) => renderEventPill(event, compact))}
                {compact && dayEvents.length > 4 && (
                  <div
                    className="text-[10px] font-black uppercase tracking-widest"
                    style={{ color: colors2000s.text.secondary }}
                  >
                    +{dayEvents.length - 4} eventos
                  </div>
                )}
                {dayEvents.length === 0 && (
                  <div
                    className="text-[10px] font-bold uppercase tracking-widest"
                    style={{ color: colors2000s.text.disabled }}
                  >
                    Sin eventos
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )

  return (
    <div className="space-y-6 animate-in fade-in duration-700">
      {confirmDialog}
      <div
        className="flex flex-col md:flex-row items-center justify-between gap-6 p-4 sm:p-6 rounded-[8px]"
        style={panelStyle}
      >
        <div className="flex items-center gap-4">
          <div
            className="w-12 h-12 rounded-[6px] text-white flex items-center justify-center flex-shrink-0"
            style={{
              background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
              boxShadow: `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`
            }}
          >
            <CalendarIcon size={24} />
          </div>
          <div>
            <h2
              className="text-2xl font-black uppercase tracking-tight leading-none mb-1"
              style={{ color: colors2000s.text.primary }}
            >
              Agenda
            </h2>
            <p
              className="text-[10px] font-black uppercase tracking-widest"
              style={{ color: colors2000s.text.secondary }}
            >
              Vistas dia, semana, mes y lista
            </p>
          </div>
        </div>

        <div
          className="flex flex-wrap items-center justify-center gap-2 sm:gap-3 p-2 rounded-[6px] border"
          style={fieldStyle}
        >
          <button
            type="button"
            onClick={() =>
              setSelectedDate((prev) =>
                subDays(prev, view === 'month' ? 30 : view === 'week' ? 7 : 1)
              )
            }
            className="w-10 h-10 flex items-center justify-center transition-all active:scale-90"
            style={buttonStyles2000s.default}
          >
            <ChevronLeft size={20} className="text-gray-600" />
          </button>
          <div className="px-4 sm:px-6 text-center min-w-[140px] sm:min-w-[200px]">
            <p
              className="text-[9px] font-black uppercase tracking-widest mb-0.5"
              style={{ color: colors2000s.orange.accent }}
            >
              {VIEW_LABELS[view]}
            </p>
            <p
              className="text-base font-black uppercase tracking-tight"
              style={{ color: colors2000s.text.primary }}
            >
              {format(selectedDate, "dd 'de' MMMM")}
            </p>
          </div>
          <button
            type="button"
            onClick={() =>
              setSelectedDate((prev) =>
                addDays(prev, view === 'month' ? 30 : view === 'week' ? 7 : 1)
              )
            }
            className="w-10 h-10 flex items-center justify-center transition-all active:scale-90"
            style={buttonStyles2000s.default}
          >
            <ChevronRight size={20} className="text-gray-600" />
          </button>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {(Object.keys(VIEW_LABELS) as CalendarView[]).map((viewKey) => (
            <button
              key={viewKey}
              type="button"
              onClick={() => setView(viewKey)}
              className="px-4 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest"
              style={view === viewKey ? buttonStyles2000s.selected : buttonStyles2000s.default}
            >
              {VIEW_LABELS[viewKey]}
            </button>
          ))}
          <button
            type="button"
            onClick={() => setIsNewAppointmentOpen(true)}
            className="px-6 py-4 rounded-xl flex items-center gap-2 font-black uppercase tracking-widest text-xs"
            style={buttonStyles2000s.selected}
          >
            <Plus size={18} /> Nuevo turno
          </button>
        </div>
      </div>

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

      {view === 'day' && renderDayView()}
      {view === 'week' && renderRangeGrid(false)}
      {view === 'month' && renderRangeGrid(true)}
      {view === 'list' && (
        <div className="space-y-3">
          {unifiedEvents.map((event) => renderEventPill(event))}
          {!unifiedEvents.length && (
            <div
              className="rounded-[6px] p-6 bg-white text-sm font-bold"
              style={{
                border: `1px solid ${colors2000s.border.light}`,
                boxShadow: colors2000s.shadows.insetDark,
                color: colors2000s.text.secondary
              }}
            >
              No hay eventos para el rango seleccionado.
            </div>
          )}
        </div>
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

        <div className="p-6 rounded-[8px] space-y-4" style={panelStyle}>
          <h3
            className="text-lg font-black uppercase tracking-tight"
            style={{ color: colors2000s.text.primary }}
          >
            Bloqueos y ausencias
          </h3>
          <div className="space-y-3">
            {timelineEvents.map((event) => (
              <div
                key={`${event.type}-${event.id}`}
                className="rounded-[6px] p-4 bg-white flex flex-col gap-3"
                style={cardStyle}
              >
                <div className="flex items-start justify-between gap-4">
                  <div>
                    <p className="text-sm font-black" style={{ color: colors2000s.text.primary }}>
                      {event.title}
                    </p>
                    <p
                      className="text-[11px] font-bold"
                      style={{ color: colors2000s.text.secondary }}
                    >
                      {formatArgentinaDayMonth(toInstantIso(event.startsAt))}{' '}
                      {formatArgentinaTime(toInstantIso(event.startsAt))} -{' '}
                      {formatArgentinaTime(toInstantIso(event.endsAt))} · {event.staffName}
                    </p>
                  </div>
                  <span
                    className="px-2 py-1 rounded-[4px] text-[10px] font-black uppercase tracking-widest"
                    style={{
                      background: event.type === 'block' ? '#ffedd5' : '#fee2e2',
                      color: event.type === 'block' ? '#c2410c' : '#b91c1c'
                    }}
                  >
                    {event.type === 'block' ? 'Bloqueo' : 'Ausencia'}
                  </span>
                </div>
                {event.type === 'block' && canManageBlocks && (
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        setBlockToEdit({
                          public_id: event.id,
                          staff_id: event.staffId,
                          starts_at: toInstantIso(event.startsAt),
                          ends_at: toInstantIso(event.endsAt),
                          reason: event.title
                        })
                      }
                      className="px-3 py-2 text-[10px] font-black uppercase tracking-widest"
                      style={buttonStyles2000s.default}
                    >
                      Editar
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        void (async () => {
                          try {
                            await deleteBlock.mutateAsync(event.id)
                            setMessage('Bloqueo desactivado')
                          } catch (error: unknown) {
                            setMessage(getErrorMessage(error, 'No se pudo desactivar'))
                          }
                        })()
                      }}
                      className="px-3 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest"
                      style={buttonStyles2000s.selected}
                    >
                      Desactivar
                    </button>
                  </div>
                )}
              </div>
            ))}
            {!timelineEvents.length && (
              <div
                className="rounded-[6px] p-6 bg-white text-sm font-bold"
                style={{ ...cardStyle, color: colors2000s.text.secondary }}
              >
                No hay bloqueos ni ausencias en el rango actual.
              </div>
            )}
          </div>
        </div>
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
