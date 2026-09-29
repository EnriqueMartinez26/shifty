import React, { useRef, useState } from 'react'

import { getErrorMessage, isStateConflictError } from '@shared/errors/getErrorMessage'
import { createUuid } from '@shared/utils/uuid'

import {
  RescheduleAppointmentModal,
  type RescheduleRequest
} from '../components/organisms/RescheduleAppointmentModal'
import { useRescheduleAppointment } from '../hooks/useCalendarAgenda'

export interface ReschedulableAppointment {
  id: string
  clientName: string
  serviceName: string
  staffName: string
  startsAt: string
}

interface RescheduleAppointmentDialogProps {
  appointment: ReschedulableAppointment
  /** Administrador de la tienda (o superadmin): puede mover fuera de horario. */
  isAdmin: boolean
  onClose: () => void
  onDone: (message: string) => void
  /** La agenda en pantalla quedo vieja: el llamador la recarga. */
  onStateConflict: () => void
}

/**
 * Envio de la reprogramacion (FF-31, D-20260929-03/04). Idempotencia por
 * intento, como el alta del panel: reintentar el MISMO pedido reusa la clave
 * (el backend devuelve lo ya hecho); otro horario, clave nueva.
 */
export const RescheduleAppointmentDialog: React.FC<RescheduleAppointmentDialogProps> = ({
  appointment,
  isAdmin,
  onClose,
  onDone,
  onStateConflict
}) => {
  const reschedule = useRescheduleAppointment()
  const [error, setError] = useState<string | null>(null)
  const lastAttemptRef = useRef<{ fp: string; key: string } | null>(null)
  // Doble click antes de que `isPending` deshabilite el boton.
  const isSubmittingRef = useRef(false)

  const submit = async (request: RescheduleRequest) => {
    if (isSubmittingRef.current) return
    isSubmittingRef.current = true
    const allowOutsideSchedule = isAdmin && request.allowOutsideSchedule
    const fp = JSON.stringify([request.newStartsAt, allowOutsideSchedule])
    const key = lastAttemptRef.current?.fp === fp ? lastAttemptRef.current.key : createUuid()
    lastAttemptRef.current = { fp, key }
    setError(null)
    try {
      await reschedule.mutateAsync({
        id: appointment.id,
        input: { newStartsAt: request.newStartsAt, idempotencyKey: key, allowOutsideSchedule }
      })
      onDone('Turno reprogramado')
    } catch (err: unknown) {
      setError(
        getErrorMessage(err, 'No se pudo reprogramar el turno.', {
          PERMISSION_DENIED: 'Solo podés reprogramar los turnos de tu agenda.',
          ...(isAdmin && {
            OUT_OF_SCHEDULE:
              'El profesional no atiende en ese horario. Marcá "Permitir fuera del horario del profesional" para moverlo igual.'
          })
        })
      )
      if (isStateConflictError(err)) onStateConflict()
    } finally {
      isSubmittingRef.current = false
    }
  }

  return (
    <RescheduleAppointmentModal
      clientName={appointment.clientName}
      serviceName={appointment.serviceName}
      staffName={appointment.staffName}
      currentStartsAt={appointment.startsAt}
      canOverrideSchedule={isAdmin}
      busy={reschedule.isPending}
      error={error}
      onSubmit={(request) => {
        void submit(request)
      }}
      onClose={onClose}
    />
  )
}
