import { fireEvent, render, screen } from '@testing-library/react'

import { SettingsSecurityTab } from './SettingsSecurityTab'

// 2026-10-02: la pestana de seguridad salio de Settings.tsx (F11b-08). El
// formulario vive en la pagina; la pestana devuelve cada tecla y el submit.

const empty = { current: '', new: '', confirm: '' }

const passwordInputs = (container: HTMLElement) =>
  Array.from(container.querySelectorAll<HTMLInputElement>('input[type="password"]'))

describe('SettingsSecurityTab', () => {
  it('cada campo devuelve el formulario completo con ese valor', () => {
    const onFormChange = jest.fn()
    const { container } = render(
      <SettingsSecurityTab
        form={{ ...empty, current: 'vieja' }}
        onFormChange={onFormChange}
        onSubmit={jest.fn()}
        saving={false}
      />
    )
    const [, nueva] = passwordInputs(container)
    if (!nueva) throw new Error('Falta el campo de la clave nueva')

    fireEvent.change(nueva, { target: { value: 'nueva-clave' } })

    expect(onFormChange).toHaveBeenCalledWith({ current: 'vieja', new: 'nueva-clave', confirm: '' })
  })

  it('el boton envia el formulario', () => {
    const onSubmit = jest.fn((event: { preventDefault: () => void }) => event.preventDefault())
    render(
      <SettingsSecurityTab
        form={empty}
        onFormChange={jest.fn()}
        onSubmit={onSubmit}
        saving={false}
      />
    )

    const form = screen.getByRole('button', { name: 'Actualizar Acceso' }).closest('form')
    if (!form) throw new Error('Falta el formulario')
    fireEvent.submit(form)

    expect(onSubmit).toHaveBeenCalledTimes(1)
  })

  it('guardando, el boton se apaga y pierde el texto', () => {
    render(
      <SettingsSecurityTab form={empty} onFormChange={jest.fn()} onSubmit={jest.fn()} saving />
    )

    expect(screen.queryByRole('button', { name: 'Actualizar Acceso' })).not.toBeInTheDocument()
    expect(screen.getByRole('button')).toBeDisabled()
  })
})
