import { useEffect, useState } from 'react'

/**
 * Espera antes de volver a pedir el codigo OTP (F4-11, 2026-09-30).
 *
 * El backend acepta 5 pedidos por hora por telefono
 * (OTP_MAX_REQUESTS_PER_HOUR): en el celular, tocar "enviar" otra vez
 * mientras el mail tardaba los gastaba y el cliente quedaba bloqueado una
 * hora. La espera arranca cuando un pedido sale bien (60 s) o cuando el
 * servidor pide un Retry-After; la comparten la reserva publica y "Mis
 * turnos".
 *
 * La espera es de UN telefono: `start` guarda la clave (los digitos del
 * telefono pedido) y el hook recibe la clave actual. Si no coinciden,
 * `secondsLeft` es 0 y se puede pedir para el otro telefono. Se calcula en el
 * render, sin un efecto que la resetee.
 *
 * Se guarda el instante de fin y no un contador: el navegador del celular
 * frena los intervalos con la pestania en segundo plano y un contador que
 * resta de a uno se atrasaria.
 */
const OTP_RESEND_COOLDOWN_SECONDS = 60

interface Cooldown {
  endsAt: number
  key: string
}

export const useResendCooldown = (currentKey: string) => {
  const [cooldown, setCooldown] = useState<Cooldown | null>(null)
  const [now, setNow] = useState(() => Date.now())

  // Sincroniza con el reloj (sistema externo): solo corre mientras hay una
  // espera activa y se limpia al terminarla o al desmontar.
  useEffect(() => {
    if (cooldown === null) return
    const { endsAt } = cooldown
    const id = window.setInterval(() => {
      const current = Date.now()
      setNow(current)
      if (current >= endsAt) setCooldown(null)
    }, 1000)
    return () => window.clearInterval(id)
  }, [cooldown])

  const secondsLeft =
    cooldown === null || cooldown.key !== currentKey
      ? 0
      : Math.max(0, Math.ceil((cooldown.endsAt - now) / 1000))

  /**
   * `forKey` por defecto es la clave del render que creo este `start`: quien
   * lo llama despues de un `await` usa la del telefono que pidio el codigo,
   * aunque la persona lo haya editado mientras tanto.
   */
  const start = (seconds = OTP_RESEND_COOLDOWN_SECONDS, forKey = currentKey) => {
    const current = Date.now()
    setNow(current)
    setCooldown({ endsAt: current + seconds * 1000, key: forKey })
  }

  return { secondsLeft, start }
}
