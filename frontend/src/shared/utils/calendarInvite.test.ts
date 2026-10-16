import {
  buildCalendarInvite,
  downloadCalendarInvite,
  escapeIcsText,
  foldIcsLine
} from './calendarInvite'

// Quien reserva sin email guarda el turno en su calendario (propuesta por
// Mateo, 2026-10-16): el .ics se arma en el navegador con la respuesta de la
// reserva.
const turno = {
  uid: 'apt-01HZX',
  // 18:00 UTC = 15:00 en Argentina
  startsAt: '2026-10-23T18:00:00Z',
  endsAt: '2026-10-23T18:30:00Z',
  summary: 'Corte en Peluquería Sol',
  description: 'Turno con Natalia.\nPara cambiarlo, escribile a Peluquería Sol.',
  now: new Date('2026-10-16T12:34:56.789Z')
}

describe('buildCalendarInvite', () => {
  it('arma un VCALENDAR con CRLF, instantes UTC y el public_id como UID', () => {
    const ics = buildCalendarInvite(turno)
    expect(ics).not.toBeNull()
    const lines = (ics ?? '').split('\r\n')
    expect(lines[0]).toBe('BEGIN:VCALENDAR')
    expect(lines).toContain('VERSION:2.0')
    expect(lines).toContain('BEGIN:VEVENT')
    expect(lines).toContain('UID:apt-01HZX')
    expect(lines).toContain('DTSTART:20261023T180000Z')
    expect(lines).toContain('DTEND:20261023T183000Z')
    expect(lines).toContain('DTSTAMP:20261016T123456Z')
    expect(lines).toContain('SUMMARY:Corte en Peluquería Sol')
    expect(lines).toContain('END:VEVENT')
    expect(ics?.endsWith('END:VCALENDAR\r\n')).toBe(true)
    // Ningun salto suelto: todas las lineas terminan en CRLF.
    expect((ics ?? '').replace(/\r\n/g, '')).not.toMatch(/[\r\n]/)
  })

  it('escapa coma, punto y coma, barra y saltos de linea del texto', () => {
    expect(escapeIcsText('Corte, barba; y algo\\mas\notra linea\r\nfin')).toBe(
      'Corte\\, barba\\; y algo\\\\mas\\notra linea\\nfin'
    )
    const ics = buildCalendarInvite({ ...turno, summary: 'Uñas, pies; manos' })
    expect(ics).toContain('SUMMARY:Uñas\\, pies\\; manos')
    expect(ics).toContain('DESCRIPTION:Turno con Natalia.\\nPara cambiarlo')
  })

  it('sin descripcion no agrega la propiedad', () => {
    expect(buildCalendarInvite({ ...turno, description: undefined })).not.toContain('DESCRIPTION')
  })

  it('devuelve null con un instante que no se puede leer', () => {
    expect(buildCalendarInvite({ ...turno, startsAt: 'no-es-una-fecha' })).toBeNull()
    expect(buildCalendarInvite({ ...turno, endsAt: '' })).toBeNull()
  })

  it('usa la hora actual como DTSTAMP si no se inyecta', () => {
    expect(buildCalendarInvite({ ...turno, now: undefined })).toMatch(/DTSTAMP:\d{8}T\d{6}Z/)
  })
})

describe('foldIcsLine', () => {
  // Octetos UTF-8: cada %XX de encodeURIComponent es uno.
  const octets = (text: string) => encodeURIComponent(text).replace(/%[0-9A-F]{2}/g, 'x').length

  it('deja igual una linea corta', () => {
    expect(foldIcsLine('SUMMARY:Corte')).toBe('SUMMARY:Corte')
  })

  it('parte en tramos de 75 octetos sin cortar un caracter multibyte', () => {
    const line = `DESCRIPTION:${'ñ'.repeat(80)}`
    const folded = foldIcsLine(line)
    const tramos = folded.split('\r\n')
    expect(tramos.length).toBeGreaterThan(1)
    for (const tramo of tramos) expect(octets(tramo)).toBeLessThanOrEqual(75)
    expect(tramos.slice(1).every((tramo) => tramo.startsWith(' '))).toBe(true)
    // Desplegar (sacar CRLF + espacio) devuelve la linea original.
    expect(folded.replace(/\r\n /g, '')).toBe(line)
  })
})

describe('downloadCalendarInvite', () => {
  const originalCreate = window.URL.createObjectURL
  const originalRevoke = window.URL.revokeObjectURL

  afterEach(() => {
    window.URL.createObjectURL = originalCreate
    window.URL.revokeObjectURL = originalRevoke
  })

  it('descarga el archivo con el nombre pedido', () => {
    const create = jest.fn(() => 'blob:turno')
    const revoke = jest.fn()
    window.URL.createObjectURL = create
    window.URL.revokeObjectURL = revoke
    const click = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    expect(downloadCalendarInvite(turno, 'turno.ics')).toBe(true)

    expect(create).toHaveBeenCalledTimes(1)
    expect(click).toHaveBeenCalledTimes(1)
    const link = click.mock.instances[0] as unknown as HTMLAnchorElement
    expect(link.download).toBe('turno.ics')
    expect(revoke).toHaveBeenCalledWith('blob:turno')
    click.mockRestore()
  })

  it('no descarga nada si el turno no se puede armar', () => {
    const create = jest.fn(() => 'blob:turno')
    window.URL.createObjectURL = create
    expect(downloadCalendarInvite({ ...turno, startsAt: '' }, 'turno.ics')).toBe(false)
    expect(create).not.toHaveBeenCalled()
  })
})
