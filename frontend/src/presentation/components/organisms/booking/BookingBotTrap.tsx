import React from 'react'

/**
 * Trampa para bots de la reserva publica (S4 del paquete antiabuso,
 * 2026-10-22). El backend rechaza con 400 `BOOKING_REJECTED` un `website` con
 * algo escrito o un `form_elapsed_ms` menor a 2500; sin los campos, pasa. No
 * es una guarda: frena al bot ingenuo que maneja el formulario. Un script que
 * llama a la API directo no manda nada y lo frenan los topes del backend.
 */
export interface BookingBotTrap {
  /** Lo escrito en el campo oculto; una persona lo deja vacio. */
  website: string
  /** Milisegundos entre que se mostro el paso de datos y el envio. */
  formElapsedMs: number
}

/** El tope que acepta el backend (`le=86_400_000`, un dia): pasarlo es un 422. */
const MAX_FORM_ELAPSED_MS = 86_400_000

/**
 * Milisegundos enteros entre `startedAt` y `now` (los dos de
 * `performance.now()`, que es monotono: un ajuste del reloj del equipo no lo
 * mueve), dentro del rango que acepta el backend. Entero porque el backend
 * pide un int y `performance.now()` trae decimales.
 */
export const formElapsedMs = (startedAt: number, now: number): number =>
  Math.min(MAX_FORM_ELAPSED_MS, Math.max(0, Math.round(now - startedAt)))

// Fuera de la pantalla y no `display: none` ni `hidden`: un bot que lee el DOM
// lo ve como un campo mas y lo llena. Una persona no lo ve.
const OFF_SCREEN: React.CSSProperties = {
  position: 'absolute',
  left: '-10000px',
  top: 'auto',
  width: 1,
  height: 1,
  overflow: 'hidden'
}

interface BookingHoneypotFieldProps {
  id: string
  value: string
  onChange: (value: string) => void
}

/**
 * El campo oculto. Fuera del orden del teclado (`tabIndex=-1`) y del arbol de
 * accesibilidad (`aria-hidden`), y sin autocompletar: el navegador de una
 * persona tampoco lo llena por ella.
 */
export const BookingHoneypotField: React.FC<BookingHoneypotFieldProps> = ({
  id,
  value,
  onChange
}) => (
  <div aria-hidden="true" style={OFF_SCREEN}>
    <label htmlFor={id}>Sitio web</label>
    <input
      id={id}
      type="text"
      name="website"
      tabIndex={-1}
      autoComplete="off"
      aria-hidden="true"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  </div>
)
