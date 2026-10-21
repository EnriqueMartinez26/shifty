import React, { useEffect, useMemo, useRef, useState } from 'react'

import { addDays, differenceInCalendarDays, format, parseISO } from 'date-fns'
import { es } from 'date-fns/locale'
import {
  Calendar as CalendarIcon,
  ChevronLeft,
  ChevronRight,
  Clock,
  Loader2,
  Sparkles,
  Users
} from 'lucide-react'

import { staffForAllServices } from '@application/mappers/PublicServiceOptionMapper'

import { usePublicAvailability, usePublicStaff } from '@presentation/hooks/usePublic'

import { getErrorMessage } from '@shared/errors/getErrorMessage'
import { formatArgentinaDate, formatArgentinaTime } from '@shared/utils/argentinaTime'

import { BookingBackButton } from './BookingBackButton'
import type { BookingSlotStaff } from './types'
import { WaitlistJoinForm } from './WaitlistJoinForm'
import { colors2000s } from '../../../../theme/colors'
import { brandColor, brandGlowShadow } from '../../../lib/brandTheme'
import { createBookingSurfaceStyle } from '../../../lib/surfaceStyles'

interface BookingStepDateTimeProps {
  storePublicId: string
  serviceId: string
  /**
   * Servicios sumados al principal en el mismo turno: la grilla mide el turno
   * entero y solo ofrece a quien hace todos.
   */
  extraServiceIds?: readonly string[]
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
  /** Invalida el horario elegido cuando se navega a otra página de fechas. */
  onDatePageChange?: () => void
}

const NO_EXTRA_SERVICES: readonly string[] = []
const PUBLIC_AVAILABILITY_DAYS_AHEAD = 120
const PUBLIC_AVAILABILITY_DATE_COUNT = PUBLIC_AVAILABILITY_DAYS_AHEAD + 1
const DATE_PAGE_SIZE = 14
const DATE_PAGE_COUNT = Math.ceil(PUBLIC_AVAILABILITY_DATE_COUNT / DATE_PAGE_SIZE)

const getPublicDate = (value: string | null, today: Date): Date => {
  if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return today
  const parsed = parseISO(value)
  if (isNaN(parsed.getTime()) || format(parsed, 'yyyy-MM-dd') !== value) return today

  const daysFromToday = differenceInCalendarDays(parsed, today)
  return daysFromToday >= 0 && daysFromToday < PUBLIC_AVAILABILITY_DATE_COUNT ? parsed : today
}

// Un 422 de la grilla con varios servicios (revision de #194): se dice por
// que en vez de mostrar una grilla vacia como si no hubiera lugar.
const AVAILABILITY_ERROR_MESSAGES: Partial<Record<string, string>> = {
  MULTI_SERVICE_DISABLED:
    'La tienda ya no toma varios servicios en un mismo turno. Para cambiarlo, escribile a la tienda.',
  SERVICES_TOO_LONG: 'Los servicios elegidos no entran en un solo turno.',
  TOO_MANY_SERVICES: 'Elegiste más servicios de los que entran en un turno.',
  STAFF_CANNOT_PERFORM_SELECTION: 'Ningún profesional hace todos los servicios elegidos.'
}

export const BookingStepDateTime: React.FC<BookingStepDateTimeProps> = ({
  storePublicId,
  serviceId,
  extraServiceIds = NO_EXTRA_SERVICES,
  staffId,
  selectedDate,
  selectedTime,
  onSelect,
  onBack,
  lockedStaffId,
  showWaitlist = true,
  heading = 'Elegí fecha y hora',
  onEmptyAvailability,
  onDatePageChange
}) => {
  // `yyyy-MM-dd` representa el día del calendario argentino, no una fecha UTC.
  const [today] = useState(() => parseISO(formatArgentinaDate(new Date().toISOString())))
  const initialDate = getPublicDate(selectedDate, today)
  const [activeDate, setActiveDate] = useState<Date | null>(initialDate)
  const [datePage, setDatePage] = useState(() =>
    Math.floor(differenceInCalendarDays(initialDate, today) / DATE_PAGE_SIZE)
  )
  const [forceAll, setForceAll] = useState(false)
  // Semilla desde la prop `staffId` (el ultimo pedido guardado en el estado
  // del wizard) para que volver desde el paso de confirmacion conserve la
  // seleccion en vez de resetear a "Cualquiera". Un profesional fijo manda.
  const [selectedStaffId, setSelectedStaffId] = useState<string | null>(lockedStaffId ?? staffId)

  // La disponibilidad publica permite desde hoy hasta 120 dias adelante.
  const dates = useMemo(() => {
    const firstDayIndex = datePage * DATE_PAGE_SIZE
    const pageLength = Math.min(DATE_PAGE_SIZE, PUBLIC_AVAILABILITY_DATE_COUNT - firstDayIndex)
    return Array.from({ length: pageLength }, (_, index) => addDays(today, firstDayIndex + index))
  }, [datePage, today])
  const firstDayNumber = datePage * DATE_PAGE_SIZE + 1
  const lastDayNumber = Math.min((datePage + 1) * DATE_PAGE_SIZE, PUBLIC_AVAILABILITY_DATE_COUNT)
  const nextPageDateCount = Math.min(
    DATE_PAGE_SIZE,
    Math.max(0, PUBLIC_AVAILABILITY_DATE_COUNT - (datePage + 1) * DATE_PAGE_SIZE)
  )
  const changeDatePage = (offset: number) => {
    const nextPage = Math.max(0, Math.min(datePage + offset, DATE_PAGE_COUNT - 1))
    if (nextPage === datePage) return
    setDatePage(nextPage)
    setActiveDate(null)
    onDatePageChange?.()
  }
  const dateStr = activeDate ? format(activeDate, 'yyyy-MM-dd') : ''

  const { data: serviceStaff, isLoading: isStaffLoading } = usePublicStaff(storePublicId, serviceId)
  // Con varios servicios, solo quien los hace todos (la grilla ya viene asi).
  const staffList = useMemo(
    () => serviceStaff && staffForAllServices(serviceStaff, extraServiceIds),
    [serviceStaff, extraServiceIds]
  )
  // La lista de espera es de UN servicio: con varios no se ofrece.
  const waitlistAvailable = showWaitlist && extraServiceIds.length === 0
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
    isFetching,
    error: availabilityError,
    refetch: refetchAvailability
  } = usePublicAvailability(
    storePublicId,
    serviceId,
    /^\d{4}-\d{2}-\d{2}$/.test(dateStr) ? dateStr : undefined,
    forceAll,
    extraServiceIds
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

  // El backend solo genera horarios dentro de las franjas de atención: si no
  // devuelve ninguno para el dia, no hay atención aunque haya profesionales
  // asignados al servicio. Un día con horarios pero ninguno libre está lleno,
  // bloqueado o dentro del aviso mínimo: ahí sí tiene sentido la lista de espera.
  const diaSinAtencion =
    availability !== undefined &&
    (staffFilterId
      ? !availability.some((slot) => slot.staff_id === staffFilterId)
      : availability.length === 0)

  const emptyReported = useRef<string | null>(null)
  useEffect(() => {
    // Sin la lista de profesionales todavia no se sabe si hay uno solo: medir
    // antes contaria dos veces el mismo dia vacio (con y sin filtro).
    if (
      !onEmptyAvailability ||
      !dateStr ||
      isStaffLoading ||
      isLoading ||
      isFetching ||
      isError ||
      !availability
    ) {
      return
    }
    const key = `${storePublicId}:${[serviceId, ...extraServiceIds].join('+')}:${dateStr}:${staffFilterId ?? ''}:${forceAll}`
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
    extraServiceIds,
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
            style={{ color: brandColor.ink }}
          >
            {heading}
          </h2>
          <p className="text-sm font-bold text-gray-500">{subtitle}</p>
        </div>
      </div>

      {!lockedStaffId && soloStaff && (
        <div>
          <div className="flex items-center gap-2 mb-1 text-xs font-black text-gray-500 uppercase tracking-widest ml-1">
            <Users size={14} style={{ color: brandColor.ink }} />
            <span>{staffLabel}</span>
          </div>
          <p className="ml-1 text-sm font-black" style={{ color: colors2000s.text.primary }}>
            {soloStaff.display_name}
          </p>
        </div>
      )}

      {!lockedStaffId && !soloStaff && (
        <div>
          <div
            className="flex items-center gap-2 mb-3 text-xs font-black uppercase tracking-widest ml-1"
            style={{ color: colors2000s.text.secondary }}
          >
            <Users size={14} style={{ color: brandColor.ink }} />
            <span>{staffLabel}</span>
          </div>

          <div
            role="region"
            aria-label={`${hayRecursos ? 'Canchas o salas' : 'Profesionales'} disponibles, desplazable horizontalmente`}
            tabIndex={0}
            className="flex gap-2 overflow-x-auto overscroll-x-contain pb-2 hide-scrollbar"
          >
            {isStaffLoading ? (
              <Loader2 className="w-5 h-5 animate-spin" style={{ color: brandColor.ink }} />
            ) : (
              staffOptions.map((option) => {
                const isSelected = selectedStaffId === option.id
                return (
                  <button
                    key={option.id ?? 'any-professional'}
                    type="button"
                    aria-pressed={isSelected}
                    onClick={() => setSelectedStaffId(option.id)}
                    className="min-h-11 min-w-11 flex items-center gap-1.5 px-3 py-2 text-xs font-black uppercase tracking-widest whitespace-nowrap border transition-all active:scale-95"
                    style={{
                      borderRadius: 6,
                      background: isSelected ? brandColor.fillGradient : '#ffffff',
                      borderColor: isSelected ? brandColor.fillBottom : colors2000s.border.default,
                      boxShadow: isSelected
                        ? colors2000s.shadows.insetLight
                        : colors2000s.shadows.insetDark,
                      color: isSelected ? brandColor.onFill : colors2000s.text.primary
                    }}
                  >
                    {option.id === null && <Sparkles className="w-3.5 h-3.5" />}
                    {option.label}
                  </button>
                )
              })
            )}
          </div>
          {staffOptions.length > 2 && (
            <p
              className="mt-1 text-[10px] font-semibold"
              style={{ color: colors2000s.text.secondary }}
            >
              Deslizá para ver más opciones.
            </p>
          )}
        </div>
      )}

      <div>
        <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 mb-3 ml-1">
          <div className="flex min-w-0 items-center gap-2 text-xs font-black text-gray-500 uppercase tracking-widest">
            <CalendarIcon size={14} style={{ color: brandColor.ink }} />
            <span>Fechas disponibles</span>
          </div>
          <span className="ml-auto text-right text-[10px] font-semibold text-gray-500">
            Deslizá para ver más
          </span>
        </div>

        <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <p
            aria-live="polite"
            className="whitespace-nowrap text-xs font-black uppercase tracking-widest text-gray-500"
          >
            Días {firstDayNumber}–{lastDayNumber} de {PUBLIC_AVAILABILITY_DATE_COUNT}
          </p>
          <div className="flex w-full items-center justify-between gap-2 sm:w-auto sm:justify-end">
            <button
              type="button"
              aria-label="Anterior: mostrar los 14 días anteriores"
              onClick={() => changeDatePage(-1)}
              disabled={datePage === 0}
              className="inline-flex min-h-11 items-center justify-center gap-1 rounded-md border px-3 py-2 text-[10px] font-black uppercase tracking-wider transition-opacity hover:opacity-80 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500 focus-visible:ring-offset-2"
              style={{
                background: colors2000s.bg.button,
                borderColor: colors2000s.border.default,
                boxShadow: colors2000s.shadows.insetLight,
                color: colors2000s.text.primary
              }}
            >
              <ChevronLeft size={14} aria-hidden="true" />
              <span>Anterior</span>
            </button>
            <button
              type="button"
              aria-label={
                datePage === DATE_PAGE_COUNT - 1
                  ? 'Siguiente: no hay más fechas disponibles'
                  : `Siguiente: mostrar los ${nextPageDateCount} días siguientes`
              }
              onClick={() => changeDatePage(1)}
              disabled={datePage === DATE_PAGE_COUNT - 1}
              className="inline-flex min-h-11 items-center justify-center gap-1 rounded-md border px-3 py-2 text-[10px] font-black uppercase tracking-wider transition-opacity hover:opacity-80 disabled:cursor-not-allowed disabled:opacity-40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-orange-500 focus-visible:ring-offset-2"
              style={{
                background: colors2000s.bg.button,
                borderColor: colors2000s.border.default,
                boxShadow: colors2000s.shadows.insetLight,
                color: colors2000s.text.primary
              }}
            >
              <span>Siguiente</span>
              <ChevronRight size={14} aria-hidden="true" />
            </button>
          </div>
        </div>

        <div
          role="group"
          aria-label="Fechas disponibles. Deslizá horizontalmente para ver más días"
          className="flex gap-3 overflow-x-auto p-4 snap-x hide-scrollbar border"
          style={createBookingSurfaceStyle()}
        >
          {dates.map((date) => {
            const formattedDate = format(date, 'yyyy-MM-dd')
            const isSelected =
              activeDate !== null && format(activeDate, 'yyyy-MM-dd') === formattedDate
            const isToday = format(date, 'yyyy-MM-dd') === format(today, 'yyyy-MM-dd')

            return (
              <button
                key={formattedDate}
                type="button"
                data-testid={`date-${formattedDate}`}
                aria-label={`${isToday ? 'Hoy, ' : ''}${format(date, "EEEE d 'de' MMMM 'de' yyyy", { locale: es })}`}
                aria-pressed={isSelected}
                onClick={() => setActiveDate(date)}
                className="min-h-11 min-w-[72px] flex flex-col items-center justify-center py-3 rounded-md border transition-all snap-center active:scale-95"
                style={{
                  background: isSelected
                    ? brandColor.fillGradient
                    : `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
                  borderColor: isSelected ? brandColor.fillBottom : colors2000s.border.default,
                  boxShadow: isSelected
                    ? `${colors2000s.shadows.insetLight}, ${brandGlowShadow}`
                    : `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
                  color: isSelected ? brandColor.onFill : colors2000s.text.primary
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
            <Clock size={14} style={{ color: brandColor.ink }} />
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
            className="min-h-11 min-w-11 px-2 flex items-center gap-2 cursor-pointer opacity-80 hover:opacity-100 transition-opacity rounded-full bg-transparent border-0 p-1 focus:outline-none focus-visible:opacity-100 focus-visible:ring-2 focus-visible:ring-orange-500 focus-visible:ring-offset-2"
          >
            <span className="text-[9px] font-black uppercase text-gray-500 tracking-wider">
              Ver todos
            </span>
            <span
              aria-hidden="true"
              className={`block w-9 h-5 rounded-full p-1 transition-colors ${forceAll ? '' : 'bg-gray-300'}`}
              style={forceAll ? { background: brandColor.fill } : undefined}
            >
              <span
                className={`block w-3 h-3 bg-white rounded-full shadow-sm transform transition-transform ${forceAll ? 'translate-x-4' : 'translate-x-0'}`}
              />
            </span>
          </button>
        </div>

        {!activeDate ? (
          <div className="text-center py-10 border" style={createBookingSurfaceStyle()}>
            <p
              className="font-black uppercase tracking-widest text-xs"
              style={{ color: colors2000s.text.secondary }}
            >
              Elegí una fecha para ver los horarios.
            </p>
          </div>
        ) : (
          <>
            {isError && availability && (
              <div
                role="status"
                className="flex flex-col items-start gap-3 rounded-md border p-4 sm:flex-row sm:items-center sm:justify-between"
                style={{
                  background: colors2000s.status.warning.bg,
                  borderColor: colors2000s.status.warning.border,
                  color: colors2000s.status.warning.text
                }}
              >
                <p className="min-w-0 break-words text-sm font-bold">
                  La información visible puede estar desactualizada.
                </p>
                <button
                  type="button"
                  onClick={() => void refetchAvailability()}
                  className="min-h-11 shrink-0 rounded-md border px-4 py-2 text-xs font-black uppercase tracking-wide"
                  style={{
                    background: `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
                    borderColor: colors2000s.border.default,
                    color: colors2000s.text.primary
                  }}
                >
                  Reintentar
                </button>
              </div>
            )}

            {isLoading || (isStaffLoading && visibleSlots.length === 0) ? (
              <div
                role="status"
                aria-label="Cargando horarios"
                className="flex flex-col items-center justify-center py-10"
              >
                <Loader2 className="w-8 h-8 animate-spin mb-4" style={{ color: brandColor.ink }} />
              </div>
            ) : isError && !availability ? (
              <div
                role="alert"
                className="text-center py-8 px-4 border space-y-3"
                style={createBookingSurfaceStyle()}
              >
                <p className="text-xs font-bold" style={{ color: colors2000s.text.primary }}>
                  {getErrorMessage(
                    availabilityError,
                    'No pudimos cargar los horarios. Probá de nuevo en unos minutos.',
                    AVAILABILITY_ERROR_MESSAGES
                  )}
                </p>
                <button
                  type="button"
                  onClick={() => {
                    void refetchAvailability()
                  }}
                  className="text-xs font-black underline"
                  style={{ color: brandColor.ink }}
                >
                  Reintentar
                </button>
              </div>
            ) : visibleSlots.length === 0 ? (
              <div className="text-center py-10 border" style={createBookingSurfaceStyle()}>
                <p
                  className="font-black uppercase tracking-widest text-xs"
                  style={{ color: colors2000s.text.secondary }}
                >
                  {diaSinAtencion ? 'Este día no hay atención.' : 'No hay turnos disponibles.'}
                </p>
                <p
                  className="text-xs mt-2 font-medium"
                  style={{ color: colors2000s.text.secondary }}
                >
                  {diaSinAtencion ? 'Probá con otro día.' : 'Probá seleccionando otro día.'}
                </p>
                {waitlistAvailable && !diaSinAtencion && (
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
              <div className="grid grid-cols-2 min-[380px]:grid-cols-3 sm:grid-cols-4 gap-3">
                {visibleSlots.map((slot) => {
                  const timeString = formatArgentinaTime(slot.starts_at)
                  const isSelected = selectedDate === dateStr && selectedTime === timeString
                  return (
                    <button
                      key={`${slot.staff_id}-${slot.start_time || slot.starts_at}`}
                      type="button"
                      aria-pressed={isSelected}
                      onClick={() =>
                        onSelect(
                          dateStr,
                          timeString,
                          slot.staff_id,
                          staffFilterId,
                          slot.starts_at,
                          {
                            name: slot.staff_name,
                            isResource: resourceIds.has(slot.staff_id)
                          }
                        )
                      }
                      className="min-h-11 min-w-0 py-2 sm:py-3 rounded-md font-black text-base sm:text-lg transition-all active:scale-95 border"
                      style={{
                        background: isSelected
                          ? brandColor.fillGradient
                          : `linear-gradient(180deg, ${colors2000s.bg.button} 0%, ${colors2000s.bg.buttonBottom} 100%)`,
                        borderColor: isSelected ? brandColor.ink : colors2000s.border.default,
                        boxShadow: isSelected
                          ? `${colors2000s.shadows.insetLight}, ${brandGlowShadow}`
                          : `${colors2000s.shadows.insetLight}, ${colors2000s.shadows.outer}`,
                        color: isSelected ? brandColor.onFill : colors2000s.text.primary
                      }}
                    >
                      <div>{timeString}</div>
                      {!staffFilterId && (
                        <div
                          className="text-[8px] uppercase tracking-widest mt-1"
                          style={{
                            color: isSelected ? brandColor.onFill : colors2000s.text.secondary
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
          </>
        )}
      </div>
    </div>
  )
}
