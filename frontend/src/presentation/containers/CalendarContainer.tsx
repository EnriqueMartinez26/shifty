import React, { useEffect, useMemo, useState } from 'react'

import {
  addDays,
  addMinutes,
  endOfMonth,
  endOfWeek,
  format,
  isSameDay,
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
  LockOpen,
  Plus,
  ShieldBan
} from 'lucide-react'

import { getErrorMessage } from '@shared/errors/getErrorMessage'

import { buttonStyles2000s, colors2000s } from '../../theme/colors'
import { useAuth } from '../context/AuthContext'
import {
  useAppointmentBlocks,
  useBlockTemplates,
  useCreateAppointmentBlock,
  useCreateRecurringAppointmentBlock,
  useDeleteAppointmentBlock,
  useUpdateAppointmentBlock
} from '../hooks/useAppointmentBlocks'
import { useCalendarAgenda, useReleaseAppointment } from '../hooks/useCalendarAgenda'
import { useManagedStaff } from '../hooks/useManagedStaff'
import { create2000sPanelStyle } from '../lib/surfaceStyles'

type CalendarView = 'day' | 'week' | 'month' | 'list'

type UnifiedCalendarEvent =
  | {
      id: string
      type: 'appointment' | 'absence'
      staffId: string
      staffName: string
      title: string
      subtitle: string
      startsAt: Date
      endsAt: Date
      status: string
    }
  | {
      id: string
      type: 'block'
      staffId: string
      staffName: string
      title: string
      subtitle: string
      startsAt: Date
      endsAt: Date
      status: 'blocked'
    }

const TIME_SLOTS = Array.from({ length: 48 }, (_, i) => {
  const date = addMinutes(startOfDay(new Date()), (i + 16) * 15)
  return format(date, 'HH:mm')
})

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

const toDateInput = (date: Date) => format(date, 'yyyy-MM-dd')
const toTimeInput = (date: Date) => format(date, 'HH:mm')

const eventPriority = (event: UnifiedCalendarEvent) => {
  if (event.type === 'block') return 0
  if (event.type === 'absence') return 1
  return 2
}

const statusStyle = (status: string) => {
  if (status === 'absent') {
    return {
      accent: '#b91c1c',
      background: 'linear-gradient(180deg, #fef2f2 0%, #fecaca 100%)',
      text: '#7f1d1d'
    }
  }
  if (status === 'pending_payment') {
    return {
      accent: '#d97706',
      background: 'linear-gradient(180deg, #fff7ed 0%, #fed7aa 100%)',
      text: '#9a3412'
    }
  }
  if (status === 'confirmed') {
    return {
      accent: '#2563eb',
      background: 'linear-gradient(180deg, #eff6ff 0%, #dbeafe 100%)',
      text: '#1d4ed8'
    }
  }
  if (status === 'completed') {
    return {
      accent: '#15803d',
      background: 'linear-gradient(180deg, #ecfdf5 0%, #dcfce7 100%)',
      text: '#166534'
    }
  }
  return {
    accent: colors2000s.orange.accent,
    background: 'linear-gradient(180deg, #ffffff 0%, #f6f8f9 100%)',
    text: colors2000s.text.primary
  }
}

export const CalendarContainer: React.FC = () => {
  const { user } = useAuth()
  const canReleaseAppointments = user?.role === 'admin' || Boolean(user?.is_global_admin)
  const [selectedDate, setSelectedDate] = useState(new Date())
  const [view, setView] = useState<CalendarView>('day')
  const [editingBlockId, setEditingBlockId] = useState<string | null>(null)
  const [message, setMessage] = useState('')
  const [blockForm, setBlockForm] = useState({
    staff_id: '',
    date: toDateInput(new Date()),
    starts_at: '10:00',
    ends_at: '11:00',
    reason: 'No atender',
    recurrence: 'none' as 'none' | 'daily' | 'weekly',
    recurrence_until: toDateInput(addDays(new Date(), 7)),
    max_occurrences: 5
  })

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

  const { data: staffMembers, isLoading: loadingStaff } = useManagedStaff()
  const agendaQuery = useCalendarAgenda(rangeKeyFrom, rangeKeyTo)
  const blocksQuery = useAppointmentBlocks()
  const templatesQuery = useBlockTemplates()
  const createBlock = useCreateAppointmentBlock()
  const createRecurringBlock = useCreateRecurringAppointmentBlock()
  const updateBlock = useUpdateAppointmentBlock()
  const deleteBlock = useDeleteAppointmentBlock()
  const releaseAppointment = useReleaseAppointment()

  useEffect(() => {
    const firstStaff = staffMembers?.[0]
    if (firstStaff && !blockForm.staff_id) {
      setBlockForm((prev) => ({ ...prev, staff_id: firstStaff.id }))
    }
  }, [blockForm.staff_id, staffMembers])

  useEffect(() => {
    setBlockForm((prev) => ({ ...prev, date: dateStr }))
  }, [dateStr])

  const blocksInRange = useMemo(() => {
    return (blocksQuery.data || []).filter((block) => {
      const startsAt = new Date(block.starts_at)
      return startsAt >= startOfDay(rangeStart) && startsAt <= addDays(startOfDay(rangeEnd), 1)
    })
  }, [blocksQuery.data, rangeEnd, rangeStart])

  const blocksForSelectedDate = useMemo(() => {
    return blocksInRange.filter((block) => block.starts_at.slice(0, 10) === dateStr)
  }, [blocksInRange, dateStr])

  const unifiedEvents = useMemo<UnifiedCalendarEvent[]>(() => {
    const appointmentEvents: UnifiedCalendarEvent[] = (agendaQuery.data || []).map(
      (appointment) => ({
        id: appointment.id,
        type: appointment.status === 'absent' ? 'absence' : 'appointment',
        staffId: appointment.staffId,
        staffName:
          staffMembers?.find((staff) => staff.id === appointment.staffId)?.displayName ||
          'Profesional',
        title: appointment.clientName,
        subtitle: appointment.serviceName,
        startsAt: appointment.timeSpan.getStartsAt(),
        endsAt: appointment.timeSpan.getEndsAt(),
        status: appointment.status
      })
    )

    const blockEvents: UnifiedCalendarEvent[] = blocksInRange.map((block) => {
      const staffName =
        staffMembers?.find((staff) => staff.id === block.staff_id)?.displayName || 'Profesional'
      return {
        id: block.public_id,
        type: 'block',
        staffId: block.staff_id,
        staffName,
        title: block.reason,
        subtitle: 'Bloqueo de agenda',
        startsAt: new Date(block.starts_at),
        endsAt: new Date(block.ends_at),
        status: 'blocked'
      }
    })

    return [...blockEvents, ...appointmentEvents].sort((a, b) => {
      const startDiff = a.startsAt.getTime() - b.startsAt.getTime()
      if (startDiff !== 0) return startDiff
      return eventPriority(a) - eventPriority(b)
    })
  }, [agendaQuery.data, blocksInRange, staffMembers])

  const appointmentCards = useMemo(() => {
    return unifiedEvents
      .filter((event) => event.type !== 'block' && isSameDay(event.startsAt, selectedDate))
      .map((event) => {
        const startMinutes = event.startsAt.getUTCHours() * 60 + event.startsAt.getUTCMinutes()
        const endMinutes = event.endsAt.getUTCHours() * 60 + event.endsAt.getUTCMinutes()
        const offsetMinutes = startMinutes - 4 * 60
        const durationMinutes = Math.max(endMinutes - startMinutes, 30)
        return {
          ...event,
          top: `${Math.max(offsetMinutes / 15, 0) * 64}px`,
          height: `${Math.max((durationMinutes / 15) * 64, 64)}px`,
          timeLabel: format(event.startsAt, 'HH:mm')
        }
      })
  }, [selectedDate, unifiedEvents])

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

  const handleEditBlock = (block: {
    public_id: string
    staff_id: string
    starts_at: string
    ends_at: string
    reason: string
  }) => {
    const startsAt = new Date(block.starts_at)
    const endsAt = new Date(block.ends_at)
    setEditingBlockId(block.public_id)
    setBlockForm({
      staff_id: block.staff_id,
      date: toDateInput(startsAt),
      starts_at: toTimeInput(startsAt),
      ends_at: toTimeInput(endsAt),
      reason: block.reason,
      recurrence: 'none',
      recurrence_until: toDateInput(addDays(startsAt, 7)),
      max_occurrences: 5
    })
  }

  const handleResetBlockForm = () => {
    setEditingBlockId(null)
    setBlockForm((prev) => ({
      ...prev,
      date: dateStr,
      starts_at: '10:00',
      ends_at: '11:00',
      reason: 'No atender',
      recurrence: 'none',
      recurrence_until: toDateInput(addDays(selectedDate, 7)),
      max_occurrences: 5
    }))
  }

  const handleSaveBlock = async () => {
    const startsAt = `${blockForm.date}T${blockForm.starts_at}:00Z`
    const endsAt = `${blockForm.date}T${blockForm.ends_at}:00Z`

    try {
      if (editingBlockId) {
        await updateBlock.mutateAsync({
          publicId: editingBlockId,
          payload: {
            staff_id: blockForm.staff_id,
            starts_at: startsAt,
            ends_at: endsAt,
            reason: blockForm.reason
          }
        })
        setMessage('Bloqueo actualizado')
      } else if (blockForm.recurrence === 'none') {
        await createBlock.mutateAsync({
          staff_id: blockForm.staff_id,
          starts_at: startsAt,
          ends_at: endsAt,
          reason: blockForm.reason
        })
        setMessage('Bloqueo creado')
      } else {
        const recurrenceUntilTime = `${blockForm.recurrence_until}T${blockForm.ends_at}:00Z`
        await createRecurringBlock.mutateAsync({
          staff_id: blockForm.staff_id,
          starts_at: startsAt,
          ends_at: endsAt,
          reason: blockForm.reason,
          recurrence: blockForm.recurrence,
          recurrence_until: recurrenceUntilTime,
          max_occurrences: blockForm.max_occurrences
        })
        setMessage('Serie de bloqueos creada')
      }
      handleResetBlockForm()
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, 'No se pudo guardar el bloqueo'))
    }
  }

  const handleReleaseAppointment = async (event: UnifiedCalendarEvent) => {
    if (event.type === 'block') return
    const confirmed = window.confirm(
      `¿Liberar el turno de ${event.title}? El enlace de pago pendiente también será vencido.`
    )
    if (!confirmed) return
    try {
      await releaseAppointment.mutateAsync(event.id)
      setMessage('Turno liberado correctamente')
    } catch (error: unknown) {
      setMessage(getErrorMessage(error, 'No se pudo liberar el turno'))
    }
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
        className={`relative rounded-2xl border ${compact ? 'p-2' : 'p-3'}`}
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
          {format(event.startsAt, 'HH:mm')} - {format(event.endsAt, 'HH:mm')} · {event.staffName}
        </p>
        {canReleaseAppointments &&
          event.type === 'appointment' &&
          ['pending', 'pending_payment'].includes(event.status) && (
            <button
              type="button"
              onClick={() => {
                void handleReleaseAppointment(event)
              }}
              disabled={releaseAppointment.isPending}
              className="mt-2 inline-flex items-center gap-1 rounded-lg bg-white px-2 py-1 text-[9px] font-black uppercase tracking-widest text-red-700 border border-red-200 disabled:opacity-50"
            >
              <LockOpen className="w-3 h-3" />
              Liberar
            </button>
          )}
      </div>
    )
  }

  const renderDayView = () => (
    <div className="rounded-[3rem] border overflow-hidden relative" style={canvasStyle}>
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
                      border:
                        idx % 2 === 0
                          ? '1px solid #2563eb'
                          : `1px solid ${colors2000s.orange.accent}`,
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
                {TIME_SLOTS.map((time) => (
                  <div
                    key={time}
                    className="h-16 border-b border-gray-50 flex items-start justify-center pt-2"
                  >
                    <span className="text-[10px] font-black text-gray-400">{time}</span>
                  </div>
                ))}
              </div>

              <div className="flex flex-1">
                {staffMembers?.map((staff) => (
                  <div
                    key={staff.id}
                    className="flex-1 min-w-[150px] relative border-r border-gray-50"
                  >
                    {TIME_SLOTS.map((time) => (
                      <div key={time} className="h-16 border-b border-gray-50/50" />
                    ))}

                    {blocksForSelectedDate
                      .filter((block) => block.staff_id === staff.id && block.is_active)
                      .map((block) => {
                        const start = new Date(block.starts_at)
                        const end = new Date(block.ends_at)
                        const startMinutes = start.getUTCHours() * 60 + start.getUTCMinutes()
                        const endMinutes = end.getUTCHours() * 60 + end.getUTCMinutes()
                        const offsetMinutes = startMinutes - 4 * 60
                        return (
                          <button
                            key={block.public_id}
                            type="button"
                            onClick={() => handleEditBlock(block)}
                            className="absolute left-2 right-2 rounded-2xl p-3 border border-l-[5px] text-left"
                            style={{
                              top: `${Math.max(offsetMinutes / 15, 0) * 64}px`,
                              height: `${Math.max(((endMinutes - startMinutes) / 15) * 64, 64)}px`,
                              background: 'linear-gradient(180deg, #fff7ed 0%, #fed7aa 100%)',
                              borderColor: '#fb923c',
                              borderLeftColor: '#c2410c',
                              boxShadow: '0 3px 6px rgba(0,0,0,0.05)'
                            }}
                          >
                            <p className="text-[8px] font-black uppercase tracking-widest text-orange-700 mb-1">
                              {block.reason}
                            </p>
                            <p className="text-[10px] font-black text-orange-900">
                              {format(start, 'HH:mm')} - {format(end, 'HH:mm')}
                            </p>
                          </button>
                        )
                      })}

                    {appointmentCards
                      .filter((event) => event.staffId === staff.id)
                      .map((event) => {
                        const style = statusStyle(event.status)
                        return (
                          <div
                            key={event.id}
                            className="absolute left-2 right-2 rounded-2xl p-3 border border-l-[5px] transition-all hover:scale-[1.02] active:scale-95 cursor-pointer flex flex-col justify-between"
                            style={{
                              top: event.top,
                              height: event.height,
                              background: style.background,
                              borderColor: colors2000s.border.default,
                              borderLeftColor: style.accent,
                              boxShadow:
                                'inset 0 1px 0 rgba(255,255,255,0.8), 0 3px 6px rgba(0,0,0,0.05)'
                            }}
                          >
                            {canReleaseAppointments &&
                              ['pending', 'pending_payment'].includes(event.status) && (
                                <button
                                  type="button"
                                  title="Liberar turno pendiente"
                                  aria-label={`Liberar turno de ${event.title}`}
                                  onClick={() => {
                                    void handleReleaseAppointment(event)
                                  }}
                                  disabled={releaseAppointment.isPending}
                                  className="absolute top-2 right-2 z-10 rounded-lg bg-white p-1.5 text-red-700 border border-red-200 disabled:opacity-50"
                                >
                                  <LockOpen className="w-3.5 h-3.5" />
                                </button>
                              )}
                            <div>
                              <p
                                className="text-[8px] font-black uppercase tracking-widest mb-0.5"
                                style={{ color: style.text }}
                              >
                                {event.subtitle}
                              </p>
                              <h4
                                className="text-[11px] font-black uppercase truncate leading-tight"
                                style={{ color: colors2000s.text.primary }}
                              >
                                {event.title}
                              </h4>
                            </div>
                            <span
                              className="self-start px-2 py-0.5 rounded-lg text-[8px] font-black tracking-widest uppercase border"
                              style={{
                                background: 'white',
                                borderColor: colors2000s.border.default,
                                boxShadow: colors2000s.shadows.insetDark,
                                color: style.text
                              }}
                            >
                              {event.timeLabel} - {event.status}
                            </span>
                          </div>
                        )
                      })}
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )

  const renderRangeGrid = (compact = false) => (
    <div className={`grid ${compact ? 'grid-cols-7' : 'md:grid-cols-2 xl:grid-cols-4'} gap-4`}>
      {daysInRange.map((day) => {
        const dayEvents = unifiedEvents.filter((event) => isSameDay(event.startsAt, day))
        return (
          <div key={day.toISOString()} className="rounded-3xl p-4 bg-white" style={cardStyle}>
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
  )

  return (
    <div className="space-y-6 animate-in fade-in duration-700">
      <div
        className="flex flex-col md:flex-row items-center justify-between gap-6 p-6 rounded-3xl"
        style={panelStyle}
      >
        <div className="flex items-center gap-4">
          <div
            className="w-12 h-12 rounded-2xl text-white flex items-center justify-center flex-shrink-0"
            style={{
              background: `linear-gradient(180deg, ${colors2000s.orange.light} 0%, ${colors2000s.orange.dark} 100%)`,
              border: `1px solid ${colors2000s.orange.accent}`,
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

        <div className="flex items-center gap-3 p-2 rounded-2xl border" style={fieldStyle}>
          <button
            onClick={() =>
              setSelectedDate((prev) =>
                subDays(prev, view === 'month' ? 30 : view === 'week' ? 7 : 1)
              )
            }
            className="w-10 h-10 rounded-xl flex items-center justify-center transition-all active:scale-90"
            style={buttonStyles2000s.default}
          >
            <ChevronLeft size={20} className="text-gray-600" />
          </button>
          <div className="px-6 text-center min-w-[200px]">
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
            onClick={() =>
              setSelectedDate((prev) =>
                addDays(prev, view === 'month' ? 30 : view === 'week' ? 7 : 1)
              )
            }
            className="w-10 h-10 rounded-xl flex items-center justify-center transition-all active:scale-90"
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
          <div
            className="px-6 py-4 rounded-xl flex items-center gap-2 font-black uppercase tracking-widest text-xs"
            style={buttonStyles2000s.selected}
          >
            <Plus size={18} /> Nuevo turno
          </div>
        </div>
      </div>

      {message && (
        <div
          className="p-4 rounded-2xl text-sm font-bold"
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
              className="rounded-2xl p-6 bg-white text-sm font-bold"
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

      <div className="grid xl:grid-cols-[1.05fr_0.95fr] gap-6">
        <div className="p-6 rounded-3xl space-y-4" style={panelStyle}>
          <div className="flex items-center gap-3">
            <ShieldBan className="w-5 h-5" style={{ color: colors2000s.orange.accent }} />
            <h3
              className="text-lg font-black uppercase tracking-tight"
              style={{ color: colors2000s.text.primary }}
            >
              Bloqueos de agenda
            </h3>
          </div>

          <div className="flex flex-wrap gap-2">
            {templatesQuery.data?.map((template) => (
              <button
                key={template.key}
                type="button"
                onClick={() => setBlockForm((prev) => ({ ...prev, reason: template.reason }))}
                className="px-3 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest"
                style={buttonStyles2000s.default}
              >
                {template.label}
              </button>
            ))}
          </div>

          <div className="grid md:grid-cols-2 gap-4">
            <select
              value={blockForm.staff_id}
              onChange={(e) => setBlockForm((prev) => ({ ...prev, staff_id: e.target.value }))}
              className="rounded-2xl px-4 py-3 font-bold outline-none"
              style={fieldStyle}
            >
              {staffMembers?.map((staff) => (
                <option key={staff.id} value={staff.id}>
                  {staff.displayName}
                </option>
              ))}
            </select>
            <input
              value={blockForm.reason}
              onChange={(e) => setBlockForm((prev) => ({ ...prev, reason: e.target.value }))}
              className="rounded-2xl px-4 py-3 font-bold outline-none"
              style={fieldStyle}
              placeholder="Motivo interno"
            />
          </div>

          <div className="grid md:grid-cols-3 gap-4">
            <input
              type="date"
              value={blockForm.date}
              onChange={(e) => setBlockForm((prev) => ({ ...prev, date: e.target.value }))}
              className="rounded-2xl px-4 py-3 font-bold outline-none"
              style={fieldStyle}
            />
            <input
              type="time"
              value={blockForm.starts_at}
              onChange={(e) => setBlockForm((prev) => ({ ...prev, starts_at: e.target.value }))}
              className="rounded-2xl px-4 py-3 font-bold outline-none"
              style={fieldStyle}
            />
            <input
              type="time"
              value={blockForm.ends_at}
              onChange={(e) => setBlockForm((prev) => ({ ...prev, ends_at: e.target.value }))}
              className="rounded-2xl px-4 py-3 font-bold outline-none"
              style={fieldStyle}
            />
          </div>

          {!editingBlockId && (
            <div className="grid md:grid-cols-3 gap-4">
              <select
                value={blockForm.recurrence}
                onChange={(e) =>
                  setBlockForm((prev) => ({
                    ...prev,
                    recurrence: e.target.value as 'none' | 'daily' | 'weekly'
                  }))
                }
                className="rounded-2xl px-4 py-3 font-bold outline-none"
                style={fieldStyle}
              >
                <option value="none">Sin recurrencia</option>
                <option value="daily">Diaria</option>
                <option value="weekly">Semanal</option>
              </select>
              <input
                type="date"
                value={blockForm.recurrence_until}
                onChange={(e) =>
                  setBlockForm((prev) => ({ ...prev, recurrence_until: e.target.value }))
                }
                className="rounded-2xl px-4 py-3 font-bold outline-none"
                style={fieldStyle}
              />
              <input
                type="number"
                min={1}
                max={60}
                value={blockForm.max_occurrences}
                onChange={(e) =>
                  setBlockForm((prev) => ({
                    ...prev,
                    max_occurrences: Number(e.target.value) || 1
                  }))
                }
                className="rounded-2xl px-4 py-3 font-bold outline-none"
                style={fieldStyle}
              />
            </div>
          )}

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => {
                void handleSaveBlock()
              }}
              disabled={!blockForm.staff_id}
              className="px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest disabled:opacity-50"
              style={buttonStyles2000s.selected}
            >
              {editingBlockId ? 'Actualizar bloqueo' : 'Guardar bloqueo'}
            </button>
            <button
              type="button"
              onClick={handleResetBlockForm}
              className="px-4 py-3 rounded-2xl text-xs font-black uppercase tracking-widest"
              style={buttonStyles2000s.default}
            >
              Limpiar
            </button>
          </div>
        </div>

        <div className="p-6 rounded-3xl space-y-4" style={panelStyle}>
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
                className="rounded-2xl p-4 bg-white flex flex-col gap-3"
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
                      {format(event.startsAt, 'dd/MM HH:mm')} - {format(event.endsAt, 'HH:mm')} ·{' '}
                      {event.staffName}
                    </p>
                  </div>
                  <span
                    className="px-2 py-1 rounded-xl text-[10px] font-black uppercase tracking-widest"
                    style={{
                      background: event.type === 'block' ? '#ffedd5' : '#fee2e2',
                      color: event.type === 'block' ? '#c2410c' : '#b91c1c'
                    }}
                  >
                    {event.type === 'block' ? 'Bloqueo' : 'Ausencia'}
                  </span>
                </div>
                {event.type === 'block' && (
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        handleEditBlock({
                          public_id: event.id,
                          staff_id: event.staffId,
                          starts_at: event.startsAt.toISOString(),
                          ends_at: event.endsAt.toISOString(),
                          reason: event.title
                        })
                      }
                      className="px-3 py-2 rounded-xl text-[10px] font-black uppercase tracking-widest"
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
                className="rounded-2xl p-6 bg-white text-sm font-bold"
                style={{ ...cardStyle, color: colors2000s.text.secondary }}
              >
                No hay bloqueos ni ausencias en el rango actual.
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
