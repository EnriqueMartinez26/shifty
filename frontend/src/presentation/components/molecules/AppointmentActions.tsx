import React from 'react'

import { Check, CheckCheck, LockOpen, UserX } from 'lucide-react'

export type AppointmentAction = 'confirm' | 'release' | 'complete' | 'absent'

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

interface ActionSpec {
  action: AppointmentAction
  label: string
  title: string
  icon: React.ReactNode
  tone: string
}

/**
 * Botones de transicion de un turno en la agenda. Refleja el grafo del
 * backend: pendiente -> confirmar (o liberar); confirmado y ya empezado ->
 * completar o ausente. Los estados terminales no muestran nada.
 */
export const availableActions = (
  status: string,
  hasStarted: boolean,
  canRelease: boolean,
  canManage: boolean
): ActionSpec[] => {
  const actions: ActionSpec[] = []
  if (status === 'pending' && canManage) {
    actions.push({
      action: 'confirm',
      label: 'Confirmar',
      title: 'Confirmar turno',
      icon: <Check className="w-3 h-3" />,
      tone: 'text-emerald-700 border-emerald-200'
    })
  }
  if (['pending', 'pending_payment'].includes(status) && canRelease) {
    actions.push({
      action: 'release',
      label: 'Liberar',
      title: 'Liberar turno pendiente',
      icon: <LockOpen className="w-3 h-3" />,
      tone: 'text-red-700 border-red-200'
    })
  }
  if (status === 'confirmed' && hasStarted && canManage) {
    actions.push(
      {
        action: 'complete',
        label: 'Completar',
        title: 'Marcar turno como completado',
        icon: <CheckCheck className="w-3 h-3" />,
        tone: 'text-blue-700 border-blue-200'
      },
      {
        action: 'absent',
        label: 'Ausente',
        title: 'El cliente no vino',
        icon: <UserX className="w-3 h-3" />,
        tone: 'text-amber-700 border-amber-200'
      }
    )
  }
  return actions
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
  const actions = availableActions(status, hasStarted, canRelease, canManage)
  if (actions.length === 0) return null
  return (
    <div className={`flex flex-wrap gap-1 ${compact ? 'mt-1' : 'mt-2'}`}>
      {actions.map((spec) => (
        <button
          key={spec.action}
          type="button"
          title={spec.title}
          aria-label={spec.title}
          onClick={(event) => {
            event.stopPropagation()
            onAction(spec.action)
          }}
          disabled={busy}
          className={`inline-flex items-center gap-1 rounded-lg bg-white px-2 py-1 text-[9px] font-black uppercase tracking-widest border disabled:opacity-50 ${spec.tone}`}
        >
          {spec.icon}
          {compact ? null : spec.label}
        </button>
      ))}
    </div>
  )
}
