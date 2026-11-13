import { fireEvent, render, screen } from '@testing-library/react'

import { SettingsNotificationsTab } from './SettingsNotificationsTab'

// 2026-10-02: la pestana de notificaciones salio de Settings.tsx (F11b-08).
// Cada interruptor devuelve solo su campo, invertido.

describe('SettingsNotificationsTab', () => {
  const value = {
    send_email_confirmation: true,
    send_email_reminders: false,
    contact_email: ''
  }

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

  // #283 (2026-11-02): el Reply-To de los mails a los clientes.
  it('el mail de contacto se ve con su ayuda y devuelve solo su campo', () => {
    const onChange = jest.fn()
    render(
      <SettingsNotificationsTab
        value={{ ...value, contact_email: 'hola@tunegocio.com' }}
        onChange={onChange}
      />
    )

    const campo = screen.getByLabelText<HTMLInputElement>('Mail de contacto')
    expect(campo.value).toBe('hola@tunegocio.com')
    const ayuda = screen.getByText(
      'Las respuestas de tus clientas a los mails de Shifty llegan acá.'
    )
    expect(campo).toHaveAttribute('aria-describedby', ayuda.id)
    expect(campo).toHaveAttribute('aria-invalid', 'false')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()

    fireEvent.change(campo, { target: { value: 'otro@tunegocio.com' } })
    expect(onChange).toHaveBeenCalledWith({ contact_email: 'otro@tunegocio.com' })
  })

  it('muestra el error del mail de contacto que le pasa la pagina', () => {
    render(
      <SettingsNotificationsTab
        value={{ ...value, contact_email: 'hola@' }}
        onChange={jest.fn()}
        contactEmailError="Ingresá un mail válido, por ejemplo hola@tunegocio.com."
      />
    )

    expect(screen.getByLabelText('Mail de contacto')).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByRole('alert')).toHaveTextContent('Ingresá un mail válido')
  })
})
