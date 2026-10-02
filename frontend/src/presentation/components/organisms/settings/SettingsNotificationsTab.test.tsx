import { fireEvent, render, screen } from '@testing-library/react'

import { SettingsNotificationsTab } from './SettingsNotificationsTab'

// 2026-10-02: la pestana de notificaciones salio de Settings.tsx (F11b-08).
// Cada interruptor devuelve solo su campo, invertido.

describe('SettingsNotificationsTab', () => {
  const value = { send_email_confirmation: true, send_email_reminders: false }

  it('muestra el estado de cada interruptor', () => {
    render(<SettingsNotificationsTab value={value} onChange={jest.fn()} />)

    expect(screen.getByRole('switch', { name: 'Email de Confirmación' })).toHaveAttribute(
      'aria-checked',
      'true'
    )
    expect(screen.getByRole('switch', { name: 'Recordatorios 24hs' })).toHaveAttribute(
      'aria-checked',
      'false'
    )
  })

  it('cada interruptor devuelve solo su campo', () => {
    const onChange = jest.fn()
    render(<SettingsNotificationsTab value={value} onChange={onChange} />)

    fireEvent.click(screen.getByRole('switch', { name: 'Email de Confirmación' }))
    fireEvent.click(screen.getByRole('switch', { name: 'Recordatorios 24hs' }))

    expect(onChange).toHaveBeenNthCalledWith(1, { send_email_confirmation: false })
    expect(onChange).toHaveBeenNthCalledWith(2, { send_email_reminders: true })
  })
})
