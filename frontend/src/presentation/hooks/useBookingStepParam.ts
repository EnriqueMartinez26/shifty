import { useLocation, useNavigate, useSearchParams } from 'react-router'

import { readStepParam, withStepParam } from '@presentation/components/organisms/booking/stepFlow'
import type { BookingStepChange } from '@presentation/components/organisms/booking/types'

/** Marca que deja un avance en el historial: desde que paso se llego. */
interface StepHistoryState {
  bookingStepFrom: number
}

const stepFrom = (state: unknown): number | undefined =>
  typeof state === 'object' &&
  state !== null &&
  typeof (state as Partial<StepHistoryState>).bookingStepFrom === 'number'
    ? (state as StepHistoryState).bookingStepFrom
    : undefined

/**
 * Paso del asistente de reserva en la URL, `?step=` (F4-15), para que "atras"
 * del navegador vuelva al paso anterior en vez de salir de la reserva.
 *
 * - `push`: avanzar deja una entrada nueva en el historial.
 * - `replace`: el salto automatico (un solo servicio) y las correcciones de un
 *   paso que no se puede mostrar no dejan entrada: "atras" no rebota a ellos.
 * - `back`: si la entrada actual la dejo un avance desde ese paso, se vuelve
 *   en el historial (igual que el boton del navegador); si no, se reemplaza.
 *
 * Sin `?step=`, el paso es `startStep` (con deep-link, el horario).
 */
export const useBookingStepParam = (startStep: number) => {
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  const navigate = useNavigate()
  const step = readStepParam(searchParams) ?? startStep

  const changeStep = ({ to, from, mode }: BookingStepChange) => {
    if (mode === 'back' && stepFrom(location.state) === to) {
      void navigate(-1)
      return
    }
    const next = (prev: URLSearchParams) => withStepParam(prev, to, startStep)
    if (mode === 'push') {
      setSearchParams(next, { state: { bookingStepFrom: from } satisfies StepHistoryState })
    } else {
      setSearchParams(next, { replace: true, state: location.state as unknown })
    }
  }

  return { step, changeStep }
}
