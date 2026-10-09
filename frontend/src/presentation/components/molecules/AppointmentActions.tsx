import React from 'react'

import { CalendarClock, Check, CheckCheck, CircleX, LockOpen, UserX } from 'lucide-react'

import { bookingActionsFor, type BookingAction } from '@domain/value-objects/BookingStatus'

export type AppointmentAction = BookingAction

interface AppointmentActionsProps {
  status: string
  /** El turno ya empezo o termino (solo entonces tiene sentido completar o marcar ausente). */
  hasStarted: boolean
  canRelease: boolean
  canManage: boolean
  /** Puede cancelar o reprogramar este turno (D-20260929-03). */
  canCancelOrReschedule: boolean
  busy: boolean
  /** Tienda suspendida: deshabilita lo que el backend responde con 402 (FF-15). */
  readOnlyReason?: string | null
  compact?: boolean
  onAction: (action: AppointmentAction) => void
}

/**
 * Lo que una tienda suspendida sigue pudiendo hacer: PATCH .../cancel y
 * .../release estan en SUSPENSION_ALLOWED_WRITES (D-20260930-12). Confirmar,
 * completar, ausente y reprogramar responden 402.
 */
const ALLOWED_WHEN_SUSPENDED: ReadonlySet<AppointmentAction> = new Set(['cancel', 'release'])

interface ActionView {
  label: string
  title: string
  icon: React.ReactNode
  tone: string
}

/**
 * Como se ve cada transicion. Cuales se ofrecen lo decide el dominio
 * (bookingActionsFor); aca solo se pinta.
 */
const ACTION_VIEWS: Record<AppointmentAction, ActionView> = {
  confirm: {
    label: 'Confirmar',
    title: 'Confirmar turno',
    icon: <Check className="w-3 h-3" />,
    tone: 'text-emerald-700 border-emerald-200'
  },
  release: {
    label: 'Liberar',
    title: 'Liberar turno pendiente',
    icon: <LockOpen className="w-3 h-3" />,
    tone: 'text-red-700 border-red-200'
  },
  cancel: {
    label: 'Cancelar',
    title: 'Cancelar turno',
    icon: <CircleX className="w-3 h-3" />,
    tone: 'text-red-700 border-red-200'
  },
  complete: {
    label: 'Completar',
    title: 'Marcar turno como completado',
    icon: <CheckCheck className="w-3 h-3" />,
    tone: 'text-blue-700 border-blue-200'
  },
  absent: {
    label: 'Ausente',
    title: 'El cliente no vino',
    icon: <UserX className="w-3 h-3" />,
    tone: 'text-amber-700 border-amber-200'
  },
  reschedule: {
    label: 'Reprogramar',
    title: 'Reprogramar turno',
    icon: <CalendarClock className="w-3 h-3" />,
    tone: 'text-slate-700 border-slate-200'
  }
}

/**
 * Blanco tactil de 40x40 (QA movil 2026-10-08: median 30x22 compactos y 24 de
 * alto con texto). En pantallas grandes los compactos de la grilla del dia y
 * del mes vuelven a su tamano: ahi no hay dedo y no entran.
 */
export const TAP_TARGET = 'min-h-10 min-w-10'
export const COMPACT_ON_DESKTOP = 'md:min-h-0 md:min-w-0'

export const AppointmentActions: React.FC<AppointmentActionsProps> = ({
  status,
  hasStarted,
  canRelease,
  canManage,
  canCancelOrReschedule,
  busy,
  readOnlyReason = null,
  compact = false,
  onAction
}) => {
  const actions = bookingActionsFor(status, {
    hasStarted,
    canRelease,
    canManage,
    canCancelOrReschedule
  })
  if (actions.length === 0) return null
  return (
    <div className={`flex flex-wrap gap-1 ${compact ? 'mt-1' : 'mt-2'}`}>
      {actions.map((action) => {
        const spec = ACTION_VIEWS[action]
        const blockedReason = ALLOWED_WHEN_SUSPENDED.has(action) ? null : readOnlyReason
        return (
          <button
            key={action}
            type="button"
            title={blockedReason ?? spec.title}
            aria-label={spec.title}
            onClick={(event) => {
              event.stopPropagation()
              onAction(action)
            }}
            disabled={busy || blockedReason !== null}
            className={`inline-flex items-center justify-center gap-1 rounded-lg bg-white px-2 py-1 text-[9px] font-black uppercase tracking-widest border disabled:opacity-50 ${TAP_TARGET} ${compact ? COMPACT_ON_DESKTOP : ''} ${spec.tone}`}
          >
            {spec.icon}
            {compact ? null : spec.label}
          </button>
        )
      })}
    </div>
  )
}
