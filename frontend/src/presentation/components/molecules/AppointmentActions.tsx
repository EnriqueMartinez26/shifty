import React from 'react'

import { Check, CheckCheck, LockOpen, UserX } from 'lucide-react'

import { bookingActionsFor, type BookingAction } from '@domain/value-objects/BookingStatus'

export type AppointmentAction = BookingAction

interface AppointmentActionsProps {
  status: string
  /** El turno ya empezo o termino (solo entonces tiene sentido completar o marcar ausente). */
  hasStarted: boolean
  canRelease: boolean
  canManage: boolean
  busy: boolean
  compact?: boolean
  onAction: (action: AppointmentAction) => void
}

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
  }
}

export const AppointmentActions: React.FC<AppointmentActionsProps> = ({
  status,
  hasStarted,
  canRelease,
  canManage,
  busy,
  compact = false,
  onAction
}) => {
  const actions = bookingActionsFor(status, { hasStarted, canRelease, canManage })
  if (actions.length === 0) return null
  return (
    <div className={`flex flex-wrap gap-1 ${compact ? 'mt-1' : 'mt-2'}`}>
      {actions.map((action) => {
        const spec = ACTION_VIEWS[action]
        return (
          <button
            key={action}
            type="button"
            title={spec.title}
            aria-label={spec.title}
            onClick={(event) => {
              event.stopPropagation()
              onAction(action)
            }}
            disabled={busy}
            className={`inline-flex items-center gap-1 rounded-lg bg-white px-2 py-1 text-[9px] font-black uppercase tracking-widest border disabled:opacity-50 ${spec.tone}`}
          >
            {spec.icon}
            {compact ? null : spec.label}
          </button>
        )
      })}
    </div>
  )
}
