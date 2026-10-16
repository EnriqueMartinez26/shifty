import React, { useEffect, useMemo, useRef, useState } from 'react'

import { addDays, format, parseISO } from 'date-fns'
import { es } from 'date-fns/locale'
import { Calendar as CalendarIcon, Clock, Loader2, Sparkles, Users } from 'lucide-react'

import { usePublicAvailability, usePublicStaff } from '@presentation/hooks/usePublic'

import { formatArgentinaTime } from '@shared/utils/argentinaTime'

import { BookingBackButton } from './BookingBackButton'
import type { BookingSlotStaff } from './types'
import { WaitlistJoinForm } from './WaitlistJoinForm'
import { colors2000s, orangeCtaGradient } from '../../../../theme/colors'
import { createBookingSurfaceStyle } from '../../../lib/surfaceStyles'

interface BookingStepDateTimeProps {
  storePublicId: string
  serviceId: string
  staffId: string | null
  selectedDate: string | null
  selectedTime: string | null
  onSelect: (
    date: string,
    time: string,
    assignedStaffId: string,
    requestedStaffId: string | null,
    startsAt: string,
    /** Quien atiende el slot (con "Cualquiera", el asignado). */
    slotStaff: BookingSlotStaff
  ) => void
  onBack: () => void
  /**
   * Profesional fijo: siembra la seleccion y oculta el selector. "Mis turnos"
   * reprograma siempre con el mismo profesional (D-20260930-06).
   */
  lockedStaffId?: string
  /** En false no se monta la lista de espera (quien reprograma ya tiene turno). */
  showWaitlist?: boolean
  heading?: string
  onEmptyAvailability?: () => void
}

export const BookingStepDateTime: React.FC<BookingStepDateTimeProps> = ({
  storePublicId,
  serviceId,
  staffId,
  selectedDate,
  selectedTime,
  onSelect,
  onBack,
  lockedStaffId,
  showWaitlist = true,
  heading = 'Elegí fecha y hora',
  onEmptyAvailability
}) => {
  const [activeDate, setActiveDate] = useState<Date>(() => {
    if (!selectedDate || selectedDate === 'invalid') return new Date()
    const parsed = parseISO(selectedDate)
    return isNaN(parsed.getTime()) ? new Date() : parsed
  })
  const [forceAll, setForceAll] = useState(false)
  // Semilla desde la prop `staffId` (el ultimo pedido guardado en el estado
  // del wizard) para que volver desde el paso de confirmacion conserve la
  // seleccion en vez de resetear a "Cualquiera". Un profesional fijo manda.
  const [selectedStaffId, setSelectedStaffId] = useState<string | null>(lockedStaffId ?? staffId)

  // 14 dias a partir de hoy, mas la fecha que vino por deep-link si cae mas
  // lejos: si no, el dia elegido cargaba sus horarios pero no se veia en la tira.
  const dates = useMemo(() => {
    const base = Array.from({ length: 14 }).map((_, i) => addDays(new Date(), i))
    if (!selectedDate || !/^\d{4}-\d{2}-\d{2}$/.test(selectedDate)) return base
    const wanted = parseISO(selectedDate)
    const ultimo = base[base.length - 1] ?? new Date()
    if (isNaN(wanted.getTime()) || wanted <= ultimo) return base
    return [...base, wanted]
  }, [selectedDate])
  const dateStr = format(activeDate, 'yyyy-MM-dd')

  const { data: staffList, isLoading: isStaffLoading } = usePublicStaff(storePublicId, serviceId)
  // Copy por tipo: una cancha o sala no es "un profesional".
  const resourceIds = new Set(
    (staffList || []).filter((staff) => staff.kind === 'resource').map((staff) => staff.public_id)
  )
  const hayRecursos = resourceIds.size > 0
  // Con un solo profesional (o cancha) para el servicio, "Cualquiera" es el
  // mismo: no hay nada que elegir y se filtra por el directamente
  // (2026-10-16, pedido de Mateo). Un profesional fijo sigue mandando.
  const soloStaff = staffList?.length === 1 ? staffList[0] : undefined
  const staffFilterId = lockedStaffId ?? soloStaff?.public_id ?? selectedStaffId
  const staffOptions = useMemo(
    () => [
      { id: null as string | null, label: 'Cualquiera' },
      ...(staffList || []).map((staff) => ({ id: staff.public_id, label: staff.display_name }))
    ],
    [staffList]
  )

  const {
    data: availability,
    isLoading,
    isError,
    isFetching
  } = usePublicAvailability(
    storePublicId,
    serviceId,
    /^\d{4}-\d{2}-\d{2}$/.test(dateStr) ? dateStr : undefined,
    forceAll
  )

  const visibleSlots = useMemo(() => {
    if (!availability) return []
    // El portal solo ofrece horarios libres: uno bloqueado u ocupado no se
    // muestra en ningun modo (2026-10-14: de noche todo el dia quedaba
    // "Bloqueado" por el aviso minimo y el cliente veia 18 botones grises).
    const libres = availability.filter((slot) => slot.status === 'available')
    if (staffFilterId) {
      return libres.filter((slot) => slot.staff_id === staffFilterId)
    }

    const firstSlotByTime = new Map<string, (typeof availability)[number]>()
    for (const slot of libres) {
      // Hora argentina del instante: starts_at es la fuente de verdad (UTC).
      const timeKey = formatArgentinaTime(slot.starts_at)
      if (!firstSlotByTime.has(timeKey)) firstSlotByTime.set(timeKey, slot)
    }
    return Array.from(firstSlotByTime.values()).sort((a, b) =>
      a.starts_at.localeCompare(b.starts_at)
    )
  }, [availability, staffFilterId])

  // El backend solo genera horarios dentro de las franjas del profesional: un
  // dia sin ninguno (para el profesional elegido, si hay uno) es un dia sin
  // atencion. Un dia con horarios pero ninguno libre esta lleno, bloqueado o
  // dentro del aviso minimo: ahi si tiene sentido la lista de espera.
  const diaSinAtencion =
    availability !== undefined &&
    !availability.some((slot) => !staffFilterId || slot.staff_id === staffFilterId)

  const emptyReported = useRef<string | null>(null)
  useEffect(() => {
    // Sin la lista de profesionales todavia no se sabe si hay uno solo: medir
    // antes contaria dos veces el mismo dia vacio (con y sin filtro).
    if (
      !onEmptyAvailability ||
      isStaffLoading ||
      isLoading ||
      isFetching ||
      isError ||
      !availability
    ) {
      return
    }
    const key = `${storePublicId}:${serviceId}:${dateStr}:${staffFilterId ?? ''}:${forceAll}`
    // availability_empty sigue midiendo todo dia sin horarios libres, tambien el
    // que no tiene atencion: es el contrato de la metrica del embudo.
    if (visibleSlots.length > 0) {
      emptyReported.current = null
    } else if (emptyReported.current !== key) {
      emptyReported.current = key
      onEmptyAvailability()
    }
  }, [
    availability,
    isStaffLoading,
    isLoading,
    isFetching,
    isError,
    visibleSlots,
    storePublicId,
    serviceId,
    dateStr,
    staffFilterId,
    forceAll,
    onEmptyAvailability
  ])

  const subtitle = soloStaff
    ? 'Elegí el día y el horario que te quede mejor.'
    : hayRecursos
      ? staffFilterId
        ? 'Busca un horario disponible para esa cancha o sala.'
        : 'Te mostramos horarios en cualquier cancha o sala disponible.'
      : staffFilterId
        ? 'Busca un horario disponible para ese profesional.'
        : 'Te mostramos horarios con cualquier profesional disponible.'
  const staffLabel = hayRecursos ? 'Cancha / sala' : 'Profesional'

  return (
    <div className="space-y-6 duration-500">
      <div className="space-y-3 mb-2">
        <BookingBackButton onBack={onBack} />
        <div>
          <h2
            className="text-2xl font-black uppercase tracking-tight"
            style={{ color: colors2000s.orange.heading }}
          >
            {heading}
          </h2>
          <p className="text-sm font-bold text-gray-500">{subtitle}</p>
        </div>
      </div>

      {!lockedStaffId && soloStaff && (
        <div>
          <div className="flex items-center gap-2 mb-1 text-xs font-black text-gray-500 uppercase tracking-widest ml-1">
            <Users size={14} className="text-orange-500" />
            <span>{staffLabel}</span>
          </div>
          <p className="ml-1 text-sm font-black" style={{ color: colors2000s.text.primary }}>
            {soloStaff.display_name}
          </p>
        </div>
      )}

      {!lockedStaffId && !soloStaff && (
        <div>
          <div className="flex items-center gap-2 mb-3 text-xs font-black text-gray-500 uppercase tracking-widest ml-1">
            <Users size={14} className="text-orange-500" />
            <span>{staffLabel}</span>
          </div>

          <div className="flex gap-2 overflow-x-auto pb-1 hide-scrollbar">
            {isStaffLoading ? (
              <Loader2 className="w-5 h-5 animate-spin text-orange-500" />
            ) : (
              staffOptions.map((option) => {
                const isSelected = selectedStaffId === option.id
                return (
                  <button
                    key={option.id ?? 'any-professional'}
                    type="button"
                    onClick={() => setSelectedStaffId(option.id)}
                    className="flex items-center gap-1.5 px-3 py-2 text-xs font-black uppercase tracking-widest whitespace-nowrap border transition-all active:scale-95"
                    style={{
                      borderRadius: 6,
                      background: isSelected ? orangeCtaGradient : '#ffffff',
                      borderColor: isSelected
                        ? colors2000s.orange.dark
                        : colors2000s.border.default,
                      boxShadow: isSelected
                        ? colors2000s.shadows.insetLight
                        : colors2000s.shadows.insetDark,
                      color: isSelected
                        ? colors2000s.text.onOrangeSelection
                        : colors2000s.text.primary
                    }}
                  >
                    {option.id === null && <Sparkles className="w-3.5 h-3.5" />}
                    {option.label}
                  </button>
                )
              })
            )}
          </div>
        </div>
      )}

      <div>
        <div className="flex items-center gap-2 mb-3 text-xs font-black text-gray-500 uppercase tracking-widest ml-1">
          <CalendarIcon size={14} className="text-orange-500" />
          <span>Fechas Disponibles</span>
        </div>

        <div
          className="flex gap-3 overflow-x-auto p-4 snap-x hide-scrollbar border"
          style={createBookingSurfaceStyle()}
        >
          {dates.map((date) => {
            const formattedDate = format(date, 'yyyy-MM-dd')
            const isSelected = format(activeDate, 'yyyy-MM-dd') === formattedDate
            const isToday = format(date, 'yyyy-MM-dd') === format(new Date(), 'yyyy-MM-dd')

            return (
              <button
                key={formattedDate}
                data-testid={`date-${formattedDate}`}
                onClick={() => setActiveDate(date)}
                className="flex flex-col items-center justify-center min-w-[72px] py-3 rounded-md border transition-all snap-center active:scale-95"
                style={{
                  background: isSelected
                    ? orangeCtaGradient
                    : `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
                  borderColor: isSelected ? colors2000s.orange.dark : colors2000s.border.default,
                  boxShadow: isSelected
                    ? `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`
                    : `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
                  color: isSelected ? colors2000s.text.onOrangeSelection : colors2000s.text.primary
                }}
              >
                <span className="text-[9px] uppercase font-black tracking-widest opacity-80">
                  {isToday ? 'Hoy' : format(date, 'EEE', { locale: es })}
                </span>
                <span className="text-2xl font-black mt-1 leading-none">{format(date, 'dd')}</span>
                <span className="text-[9px] font-black uppercase tracking-widest opacity-80 mt-1">
                  {format(date, 'MMM', { locale: es })}
                </span>
              </button>
            )
          })}
        </div>
      </div>

      <div className="pt-2">
        <div className="flex items-center justify-between mb-4 ml-1">
          <div className="flex items-center gap-2 text-xs font-black text-gray-500 uppercase tracking-widest">
            <Clock size={14} className="text-orange-500" />
            <span>Horarios Disponibles</span>
          </div>
          {/* Un boton real con role="switch": entra en el orden de Tab y
              Enter/Espacio lo activan. Antes era un div con onClick dentro de
              un label sin control, inalcanzable por teclado (F11a-09). */}
          <button
            type="button"
            role="switch"
            aria-checked={forceAll}
            onClick={() => setForceAll(!forceAll)}
            className="flex items-center gap-2 cursor-pointer opacity-80 hover:opacity-100 transition-opacity rounded-full bg-transparent border-0 p-1 focus:outline-none focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-orange-500 focus-visible:ring-offset-2"
          >
            <span className="text-[9px] font-black uppercase text-gray-500 tracking-wider">
              Ver todos
            </span>
            <span
              aria-hidden="true"
              className={`block w-9 h-5 rounded-full p-1 transition-colors ${forceAll ? 'bg-orange-500' : 'bg-gray-300'}`}
            >
              <span
                className={`block w-3 h-3 bg-white rounded-full shadow-sm transform transition-transform ${forceAll ? 'translate-x-4' : 'translate-x-0'}`}
              />
            </span>
          </button>
        </div>

        {isLoading ? (
          <div className="flex flex-col items-center justify-center py-10">
            <Loader2 className="w-8 h-8 animate-spin text-orange-500 mb-4" />
          </div>
        ) : visibleSlots.length === 0 ? (
          <div className="text-center py-10 border" style={createBookingSurfaceStyle()}>
            <p className="font-black text-gray-400 uppercase tracking-widest text-xs">
              {diaSinAtencion ? 'Este día no hay atención.' : 'No hay turnos disponibles.'}
            </p>
            <p className="text-xs text-gray-400 mt-2 font-medium">
              {diaSinAtencion ? 'Probá con otro día.' : 'Probá seleccionando otro día.'}
            </p>
            {showWaitlist && !diaSinAtencion && (
              <div className="px-4 text-left">
                <WaitlistJoinForm
                  key={dateStr}
                  storePublicId={storePublicId}
                  serviceId={serviceId}
                  staffId={staffId}
                  date={dateStr}
                />
              </div>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-3 sm:grid-cols-4 gap-3">
            {visibleSlots.map((slot) => {
              const timeString = formatArgentinaTime(slot.starts_at)
              const isSelected = selectedDate === dateStr && selectedTime === timeString
              return (
                <button
                  key={`${slot.staff_id}-${slot.start_time || slot.starts_at}`}
                  onClick={() =>
                    onSelect(dateStr, timeString, slot.staff_id, staffFilterId, slot.starts_at, {
                      name: slot.staff_name,
                      isResource: resourceIds.has(slot.staff_id)
                    })
                  }
                  className="py-3 rounded-md font-black text-lg transition-all active:scale-95 border"
                  style={{
                    background: isSelected
                      ? orangeCtaGradient
                      : `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
                    borderColor: isSelected
                      ? colors2000s.orange.accent
                      : colors2000s.border.default,
                    boxShadow: isSelected
                      ? `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outerOrange}`
                      : `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
                    color: isSelected
                      ? colors2000s.text.onOrangeSelection
                      : colors2000s.text.primary
                  }}
                >
                  <div>{timeString}</div>
                  {!staffFilterId && (
                    <div
                      className="text-[8px] uppercase tracking-widest mt-1"
                      style={{
                        color: isSelected
                          ? colors2000s.text.onOrangeSelection
                          : colors2000s.text.secondary
                      }}
                    >
                      {slot.staff_name}
                    </div>
                  )}
                </button>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
