/**
 * Archivo de calendario (.ics, RFC 5545) armado en el navegador.
 *
 * Quien reserva sin email no recibe recordatorios (propuesta por Mateo,
 * 2026-10-16): la pantalla de exito le ofrece guardar el turno en su
 * calendario. No pasa por el backend: todo lo que hace falta ya vino en la
 * respuesta de la reserva.
 */

interface CalendarInviteInput {
  /** Identificador estable del evento: el public_id del turno. */
  uid: string
  /** Instantes ISO (UTC) del turno, tal como los devuelve la API. */
  startsAt: string
  endsAt: string
  summary: string
  description?: string
  /** Sello de creacion; por defecto, ahora. Se inyecta para probarlo. */
  now?: Date
}

const CRLF = '\r\n'
// RFC 5545 3.1: una linea de contenido no pasa de 75 octetos; la continuacion
// empieza con un espacio, que cuenta dentro de los 75.
const MAX_LINE_OCTETS = 75
const UID_DOMAIN = 'shifty-ar.tech'
const REVOKE_DELAY_MS = 1000

/** `20261023T180000Z`, o null si el instante no se puede leer. */
const toIcsUtc = (iso: string | Date): string | null => {
  const date = typeof iso === 'string' ? new Date(iso) : iso
  if (Number.isNaN(date.getTime())) return null
  return date
    .toISOString()
    .replace(/\.\d{3}Z$/, 'Z')
    .replace(/[-:]/g, '')
}

/** Texto de una propiedad: barra invertida, `;`, `,` y saltos de linea escapados. */
export const escapeIcsText = (value: string): string =>
  value
    .replace(/\\/g, '\\\\')
    .replace(/;/g, '\\;')
    .replace(/,/g, '\\,')
    .replace(/\r\n|\r|\n/g, '\\n')

const utf8Octets = (char: string): number => {
  const codePoint = char.codePointAt(0) ?? 0
  if (codePoint < 0x80) return 1
  if (codePoint < 0x800) return 2
  if (codePoint < 0x10000) return 3
  return 4
}

/** Parte una linea larga en tramos de a lo sumo 75 octetos, sin cortar un caracter. */
export const foldIcsLine = (line: string): string => {
  const parts: string[] = []
  let current = ''
  let octets = 0
  for (const char of line) {
    const size = utf8Octets(char)
    // La continuacion arranca con un espacio: tiene un octeto menos de lugar.
    const limit = parts.length === 0 ? MAX_LINE_OCTETS : MAX_LINE_OCTETS - 1
    if (octets + size > limit) {
      parts.push(current)
      current = ''
      octets = 0
    }
    current += char
    octets += size
  }
  parts.push(current)
  return parts.join(`${CRLF} `)
}

/** El .ics de un turno, o null si sus instantes no se pueden leer. */
export const buildCalendarInvite = (input: CalendarInviteInput): string | null => {
  const start = toIcsUtc(input.startsAt)
  const end = toIcsUtc(input.endsAt)
  const stamp = toIcsUtc(input.now ?? new Date())
  if (!start || !end || !stamp) return null
  const lines = [
    'BEGIN:VCALENDAR',
    'VERSION:2.0',
    'PRODID:-//Shifty//Turnos//ES',
    'CALSCALE:GREGORIAN',
    'METHOD:PUBLISH',
    'BEGIN:VEVENT',
    // RFC 5545 pide un UID unico global: el public_id con el dominio.
    `UID:${escapeIcsText(`${input.uid}@${UID_DOMAIN}`)}`,
    `DTSTAMP:${stamp}`,
    `DTSTART:${start}`,
    `DTEND:${end}`,
    `SUMMARY:${escapeIcsText(input.summary)}`,
    ...(input.description ? [`DESCRIPTION:${escapeIcsText(input.description)}`] : []),
    'END:VEVENT',
    'END:VCALENDAR'
  ]
  return lines.map(foldIcsLine).join(CRLF) + CRLF
}

/**
 * Descarga el .ics: el navegador lo abre con la app de calendario del
 * telefono o lo guarda. Devuelve false si no se pudo armar.
 */
export const downloadCalendarInvite = (input: CalendarInviteInput, filename: string): boolean => {
  const content = buildCalendarInvite(input)
  if (!content) return false
  const url = window.URL.createObjectURL(
    new Blob([content], { type: 'text/calendar;charset=utf-8' })
  )
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  // Revocar en el mismo tick puede abortar la descarga (Firefox, Safari de
  // iOS): se libera despues.
  window.setTimeout(() => window.URL.revokeObjectURL(url), REVOKE_DELAY_MS)
  return true
}
