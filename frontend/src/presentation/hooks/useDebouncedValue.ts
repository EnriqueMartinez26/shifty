import { useEffect, useState } from 'react'

/**
 * Devuelve `value` recien cuando deja de cambiar durante `ms` (F4-06,
 * 2026-09-30).
 *
 * La vista previa de la seña hacia una request por tecla del telefono. El
 * valor inicial pasa sin espera: un telefono ya completo al llegar al paso
 * consulta de entrada. Cada cambio reinicia la espera y solo llega el ultimo.
 */
export const useDebouncedValue = <T>(value: T, ms: number): T => {
  const [debounced, setDebounced] = useState(value)

  // Sincroniza con el temporizador (sistema externo): se limpia en cada
  // cambio y al desmontar, asi un valor viejo nunca pisa uno nuevo.
  useEffect(() => {
    const id = window.setTimeout(() => setDebounced(value), ms)
    return () => window.clearTimeout(id)
  }, [value, ms])

  return debounced
}
