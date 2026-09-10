import { render, screen } from '@testing-library/react'

import { ClientWhatsAppButton } from './ClientWhatsAppButton'

const message = {
  clientName: 'Carla',
  serviceName: 'Corte',
  staffName: 'Ana',
  startsAt: new Date('2026-09-15T13:00:00Z'),
  storeName: 'Sol',
  rebookUrl: 'https://app.test/b/sol?service=svc-1&staff=st-1'
}

describe('ClientWhatsAppButton', () => {
  it('para un turno confirmado arma el recordatorio', () => {
    render(<ClientWhatsAppButton phone="+5491155550031" status="confirmed" message={message} />)

    const link = screen.getByRole('link', { name: 'Recordar por WhatsApp' })
    expect(link).toHaveAttribute('target', '_blank')
    const href = link.getAttribute('href') ?? ''
    expect(href.startsWith('https://wa.me/5491155550031?text=')).toBe(true)
    expect(decodeURIComponent(href)).toContain('15/09/2026 a las 10:00 hs')
  })

  it('para un turno completado invita a volver con el deep-link', () => {
    render(<ClientWhatsAppButton phone="5491155550031" status="completed" message={message} />)

    const link = screen.getByRole('link', { name: 'Invitar a volver' })
    expect(decodeURIComponent(link.getAttribute('href') ?? '')).toContain(message.rebookUrl)
  })

  it('no muestra nada para un turno cancelado ni sin telefono', () => {
    const { container } = render(
      <ClientWhatsAppButton phone="5491155550031" status="cancelled" message={message} />
    )
    expect(container.innerHTML).toBe('')
    const sinTelefono = render(
      <ClientWhatsAppButton phone="" status="confirmed" message={message} />
    )
    expect(sinTelefono.container.innerHTML).toBe('')
  })
})
