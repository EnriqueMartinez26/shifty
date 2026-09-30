import { useEffect, useState } from 'react'

/**
 * Espera antes de volver a pedir el codigo OTP (F4-11, 2026-09-30).
 *
 * El backend acepta 5 pedidos por hora por telefono
 * (OTP_MAX_REQUESTS_PER_HOUR): en el celular, tocar "enviar" otra vez
 * mientras el mail tardaba los gastaba y el cliente quedaba bloqueado una
 * hora. La espera arranca solo cuando un pedido sale bien; la comparten la
 * reserva publica y "Mis turnos".
 *
 * Se guarda el instante de fin y no un contador: el navegador del celular
 * frena los intervalos con la pestania en segundo plano y un contador que
 * resta de a uno se atrasaria.
 */
const OTP_RESEND_COOLDOWN_SECONDS = 60

export const useResendCooldown = () => {
  const [endsAt, setEndsAt] = useState<number | null>(null)
  const [now, setNow] = useState(() => Date.now())

  // Sincroniza con el reloj: solo corre mientras hay una espera activa.
  useEffect(() => {
    if (endsAt === null) return
    const id = window.setInterval(() => {
      const current = Date.now()
      setNow(current)
      if (current >= endsAt) setEndsAt(null)
    }, 1000)
    return () => window.clearInterval(id)
  }, [endsAt])

  const remainingSeconds = endsAt === null ? 0 : Math.max(0, Math.ceil((endsAt - now) / 1000))

  const start = () => {
    const current = Date.now()
    setNow(current)
    setEndsAt(current + OTP_RESEND_COOLDOWN_SECONDS * 1000)
  }

  return { remainingSeconds, start }
}
