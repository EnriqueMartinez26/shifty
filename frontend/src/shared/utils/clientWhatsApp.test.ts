import {
  buildClientMessage,
  buildRebookUrl,
  buildWaMeUrl,
  clientMessageKindFor
} from './clientWhatsApp'

const base = {
  clientName: 'Carla',
  serviceName: 'Corte',
  staffName: 'Ana',
  // 13:00 UTC = 10:00 en Argentina
  startsAt: new Date('2026-09-15T13:00:00Z'),
  storeName: 'Peluqueria Sol'
}

describe('clientWhatsApp', () => {
  it('el recordatorio muestra fecha y hora argentina', () => {
    const texto = buildClientMessage('reminder', base)
    expect(texto).toContain('Hola Carla!')
    expect(texto).toContain('Corte con Ana')
    expect(texto).toContain('15/09/2026 a las 10:00 hs')
    expect(texto).toContain('Peluqueria Sol')
  })

  it('la invitacion post-turno lleva el deep-link de re-reserva', () => {
    const link = buildRebookUrl('https://app.shifty.com/', 'sol', 'svc-1', 'st-1')
    expect(link).toBe('https://app.shifty.com/b/sol?service=svc-1&staff=st-1')
    const texto = buildClientMessage('rebook', { ...base, rebookUrl: link })
    expect(texto).toContain('Gracias por venir a Peluqueria Sol')
    expect(texto).toContain(link)
  })

  it('elige el mensaje segun el estado del turno', () => {
    expect(clientMessageKindFor('pending')).toBe('reminder')
    expect(clientMessageKindFor('confirmed')).toBe('reminder')
    expect(clientMessageKindFor('completed')).toBe('rebook')
    expect(clientMessageKindFor('cancelled')).toBeNull()
    expect(clientMessageKindFor('absent')).toBeNull()
  })

  it('arma el link wa.me con el telefono limpio y el texto codificado', () => {
    const url = buildWaMeUrl('+54 9 11 5555-0031', 'Hola & chau')
    expect(url).toBe('https://wa.me/5491155550031?text=Hola%20%26%20chau')
  })
})
