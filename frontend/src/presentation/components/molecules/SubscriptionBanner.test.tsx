import { render, screen } from '@testing-library/react'

import type { StoreSubscriptionStatus } from '@application/services/StoreSettingsService'

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

describe('SubscriptionBanner', () => {
  it('ofrece el WhatsApp de soporte con el nombre de la tienda', () => {
    render(
      <SubscriptionBanner
        subscription={{ ...base, status: 'suspended', blocks_writes: true }}
        storeName="Peluqueria Sol"
      />
    )

    const link = screen.getByRole('link', { name: 'Renovar por WhatsApp' })
    expect(decodeURIComponent(link.getAttribute('href') ?? '')).toContain('Peluqueria Sol')
  })

  it('no renderiza nada cuando no hay nada que avisar', () => {
    const { container } = render(<SubscriptionBanner subscription={base} />)
    expect(container.innerHTML).toBe('')
  })
})
