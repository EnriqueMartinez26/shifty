import { createRef, type ComponentProps } from 'react'

import { fireEvent, render, screen, within } from '@testing-library/react'

import type { GatewayConfig } from '@application/services/PaymentsService'

import { ForbiddenError } from '@shared/errors/ForbiddenError'

import { SettingsPaymentsTab } from './SettingsPaymentsTab'

// 2026-10-02: la pestana de Mercado Pago salio de Settings.tsx (F11b-08). No
// llama a ninguna mutacion: conectar, renovar, desconectar y guardar llegan
// como callbacks de la pagina (D-58).

type TabProps = ComponentProps<typeof SettingsPaymentsTab>

const idle = { connect: false, refresh: false, disconnect: false }

const renderTab = (overrides: Partial<TabProps> = {}) => {
  const props: TabProps = {
    gateway: { provider: 'mercadopago', configured: false, oauth_supported: true },
    pending: idle,
    onConnect: jest.fn(),
    onRefresh: jest.fn(),
    onDisconnect: jest.fn(),
    justConnected: false,
    value: { allow_manual_coordination: true, deposit_policy: '' },
    onChange: jest.fn(),
    onSave: jest.fn(),
    saveDisabled: false,
    saveStatus: 'idle',
    saveBlockedNotice: null,
    ...overrides
  }
  render(<SettingsPaymentsTab {...props} />)
  return props
}

describe('SettingsPaymentsTab', () => {
  it('sin conectar ofrece "Conectar" y lo delega', () => {
    const props = renderTab()

    fireEvent.click(screen.getByRole('button', { name: 'Conectar con Mercado Pago' }))

    expect(props.onConnect).toHaveBeenCalledTimes(1)
    expect(screen.getByText('Pendiente')).toBeInTheDocument()
  })

  it('conectando, el boton se apaga y lo dice', () => {
    renderTab({ pending: { ...idle, connect: true } })

    expect(screen.getByRole('button', { name: 'Conectando...' })).toBeDisabled()
  })

  it('conectada, renovar y desconectar se delegan', () => {
    const gateway: GatewayConfig = {
      provider: 'mercadopago',
      configured: true,
      oauth_user_id: '42',
      oauth_supported: true
    }
    const props = renderTab({ gateway, justConnected: true })

    fireEvent.click(screen.getByRole('button', { name: 'Renovar acceso' }))
    fireEvent.click(screen.getByRole('button', { name: 'Desconectar' }))

    expect(props.onRefresh).toHaveBeenCalledTimes(1)
    expect(props.onDisconnect).toHaveBeenCalledTimes(1)
    expect(screen.getByText('Cuenta Mercado Pago 42')).toBeInTheDocument()
    expect(screen.getByText('La cuenta quedó conectada correctamente.')).toBeInTheDocument()
  })

  it('las condiciones devuelven solo su campo y "Guardar condiciones" se delega', () => {
    const props = renderTab()

    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.change(screen.getByPlaceholderText(/La seña equivale al 30%/), {
      target: { value: 'Política' }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Guardar condiciones' }))

    expect(props.onChange).toHaveBeenNthCalledWith(1, { allow_manual_coordination: false })
    expect(props.onChange).toHaveBeenNthCalledWith(2, { deposit_policy: 'Política' })
    expect(props.onSave).toHaveBeenCalledTimes(1)
  })

  it('en solo lectura "Guardar condiciones" lleva el motivo y conectar sigue', () => {
    renderTab({ saveDisabled: true, readOnlyReason: 'Tienda suspendida' })

    const guardar = screen.getByRole('button', { name: 'Guardar condiciones' })
    expect(guardar).toBeDisabled()
    expect(guardar).toHaveAttribute('title', 'Tienda suspendida')
    expect(screen.getByRole('button', { name: 'Conectar con Mercado Pago' })).not.toBeDisabled()
  })

  // 2026-10-12: con los cobros apagados el orden importa (el backend no deja
  // prenderlos sin la politica guardada), asi que el aviso lo lista.
  it('con los cobros apagados lista los tres pasos en orden', () => {
    renderTab({
      gatewayError: new ForbiddenError('x', { errorCode: 'FEATURE_DISABLED', statusCode: 403 })
    })

    const steps = within(screen.getByRole('status')).getAllByRole('listitem')
    expect(steps.map((step) => step.textContent)).toEqual([
      'Escribí y guardá acá abajo tu política de seña.',
      'Activá «Cobros online y señas» en la pestaña Funciones.',
      'Volvé a esta pestaña y conectá Mercado Pago.'
    ])
  })

  it('el campo de la politica tiene su etiqueta y recibe la ref de la pagina', () => {
    const policyFieldRef = createRef<HTMLTextAreaElement>()
    renderTab({ policyFieldRef })

    expect(policyFieldRef.current).toBe(
      screen.getByLabelText('Política de seña, cancelación y reembolso')
    )
  })
})
