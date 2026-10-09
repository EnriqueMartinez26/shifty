import { render, screen } from '@testing-library/react'

import type { StoreSubscriptionStatus } from '@application/services/StoreSettingsService'

import { getContactEnv } from '@shared/utils/env'

import { SubscriptionBanner, subscriptionBanner } from './SubscriptionBanner'

const base: StoreSubscriptionStatus = {
  status: 'active',
  plan_name: 'Plan Pro',
  current_period_end: '2026-09-20T12:00:00+00:00',
  days_left: 10,
  grace_until: null,
  warn: false,
  blocks_writes: false
}

describe('subscriptionBanner', () => {
  it('no dice nada con el plan al dia, sin plan o cancelado', () => {
    expect(subscriptionBanner(undefined)).toBeNull()
    expect(subscriptionBanner(base)).toBeNull()
    expect(subscriptionBanner({ ...base, status: 'none', plan_name: null })).toBeNull()
    expect(subscriptionBanner({ ...base, status: 'cancelled' })).toBeNull()
  })

  it('avisa con los dias que faltan dentro de la ventana', () => {
    expect(subscriptionBanner({ ...base, warn: true, days_left: 3 })?.title).toBe(
      'Tu plan vence en 3 días'
    )
    expect(subscriptionBanner({ ...base, warn: true, days_left: 1 })?.title).toBe(
      'Tu plan vence mañana'
    )
    expect(subscriptionBanner({ ...base, warn: true, days_left: 0 })?.title).toBe(
      'Tu plan vence hoy'
    )
  })

  it('vencida muestra hasta cuando dura la gracia', () => {
    const contenido = subscriptionBanner({
      ...base,
      status: 'past_due',
      days_left: -2,
      grace_until: '2026-09-27'
    })
    expect(contenido?.tone).toBe('blocked')
    expect(contenido?.detail).toContain('27/09/2026')
  })

  it('suspendida explica que el panel quedo en solo lectura', () => {
    const contenido = subscriptionBanner({
      ...base,
      status: 'suspended',
      blocks_writes: true
    })
    expect(contenido?.tone).toBe('blocked')
    expect(contenido?.detail).toContain('solo lectura')
  })
})

// 2026-10-03: el numero era un placeholder en el codigo (5493513000000). El real
// es un telefono personal y el repo es publico: llega por configuracion del
// build (VITE_SUPPORT_WHATSAPP). Aca, valores de prueba.
describe('SubscriptionBanner', () => {
  const suspendida = { ...base, status: 'suspended' as const, blocks_writes: true }

  afterEach(() => {
    jest.mocked(getContactEnv).mockReturnValue({})
  })

  it('con el WhatsApp configurado ofrece renovar por wa.me con el nombre de la tienda', () => {
    jest.mocked(getContactEnv).mockReturnValue({ supportWhatsApp: '5493510000000' })
    render(<SubscriptionBanner subscription={suspendida} storeName="Peluqueria Sol" />)

    const link = screen.getByRole('link', { name: 'Renovar por WhatsApp' })
    expect(link.getAttribute('href')).toMatch(/^https:\/\/wa\.me\/5493510000000\?text=/)
    expect(decodeURIComponent(link.getAttribute('href') ?? '')).toContain('Peluqueria Sol')
  })

  it('sin WhatsApp ni email configurados no hay link: queda un texto neutro', () => {
    render(<SubscriptionBanner subscription={suspendida} storeName="Peluqueria Sol" />)

    expect(screen.queryByRole('link')).toBeNull()
    expect(screen.getByText('Escribinos para renovar')).toBeInTheDocument()
  })

  it('un WhatsApp invalido no arma un link roto', () => {
    jest.mocked(getContactEnv).mockReturnValue({ supportWhatsApp: '[[COMPLETAR]]' })
    render(<SubscriptionBanner subscription={suspendida} />)

    expect(screen.queryByRole('link', { name: 'Renovar por WhatsApp' })).toBeNull()
    expect(screen.getByText('Escribinos para renovar')).toBeInTheDocument()
  })

  it('sin WhatsApp pero con email, el texto neutro escribe al email', () => {
    jest.mocked(getContactEnv).mockReturnValue({ contactEmail: 'responsable@example.com' })
    render(<SubscriptionBanner subscription={suspendida} />)

    expect(screen.getByRole('link', { name: 'Escribinos para renovar' })).toHaveAttribute(
      'href',
      'mailto:responsable@example.com'
    )
  })

  it('no renderiza nada cuando no hay nada que avisar', () => {
    const { container } = render(<SubscriptionBanner subscription={base} />)
    expect(container.innerHTML).toBe('')
  })
})
