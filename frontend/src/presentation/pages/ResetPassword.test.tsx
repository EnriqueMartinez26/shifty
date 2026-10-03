import { mdiStore } from '@mdi/js'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import { ValidationError } from '@shared/errors'

import ResetPasswordPage from './ResetPassword'
import { cssValue } from '../../test/cssValue'
import { colors2000s } from '../../theme/colors'

const mockMutateAsync = jest.fn()

jest.mock('../hooks/useResetPassword', () => ({
  useResetPassword: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false
  })
}))

describe('ResetPasswordPage', () => {
  // F11b-14: pins the `AuthShell` markup as rendered by this page.
  it('renders the branding, card, back-to-login link and footer', () => {
    render(
      <MemoryRouter initialEntries={['/reset-password?token=abc']}>
        <ResetPasswordPage />
      </MemoryRouter>
    )

    const heading = screen.getByRole('heading', { level: 1, name: 'Restablecer contraseña' })
    expect(heading.className).toBe('text-3xl font-bold tracking-tight mb-1')
    expect(heading.style.color).toBe(cssValue('color', colors2000s.orange.accent))

    const subtitle = screen.getByText('Definí una nueva contraseña para tu cuenta.')
    expect(subtitle.tagName).toBe('P')
    expect(subtitle.className).toBe('text-sm font-medium')
    expect(subtitle.style.color).toBe(cssValue('color', colors2000s.text.secondary))

    const header = heading.parentElement as HTMLElement
    expect(header.className).toBe('flex flex-col items-center mb-8 text-center')

    const iconBox = header.firstElementChild as HTMLElement
    expect(iconBox.className).toBe(
      'w-16 h-16 rounded-2xl flex items-center justify-center mb-4 rotate-3 relative overflow-hidden'
    )
    expect(iconBox.style.border).toBe(cssValue('border', `1px solid ${colors2000s.orange.accent}`))
    expect((iconBox.firstElementChild as HTMLElement).className).toBe(
      'absolute top-0 left-0 right-0 h-1/2 bg-white/20 pointer-events-none'
    )
    const icon = iconBox.querySelector('svg') as SVGElement
    expect(icon).toHaveAttribute('aria-hidden', 'true')
    expect(icon).toHaveAttribute('width', '30')
    expect(icon.querySelector('path')).toHaveAttribute('d', mdiStore)

    const column = header.parentElement as HTMLElement
    expect(column.className).toBe('w-full max-w-md p-8 relative z-10')
    expect((column.parentElement as HTMLElement).className).toBe(
      'min-h-screen w-full flex items-center justify-center relative overflow-hidden px-4'
    )

    const form = screen.getByLabelText('Nueva contraseña').closest('form') as HTMLFormElement
    const card = form.parentElement as HTMLElement
    expect(card.className).toBe('p-8 rounded-3xl')
    expect(card.style.border).toBe(cssValue('border', `1px solid ${colors2000s.border.default}`))

    const back = screen.getByRole('link', { name: 'Volver a iniciar sesión' })
    expect(back).toHaveAttribute('href', '/login')
    expect(back.className).toBe(
      'inline-flex items-center gap-2 text-sm font-bold transition-colors'
    )
    expect(back.style.color).toBe(cssValue('color', colors2000s.orange.accent))
    expect(back.querySelector('svg')).not.toBeNull()
    const footer = back.parentElement as HTMLElement
    expect(footer.className).toBe('mt-8 pt-8 text-center')
    expect(footer.style.borderTop).toBe(
      cssValue('borderTop', `1px solid ${colors2000s.border.light}`)
    )
    expect(card.lastElementChild).toBe(footer)
    expect(footer.previousElementSibling).toBe(form)

    const copyright = screen.getByText('Copyright 2026 Shifty SaaS. Todos los derechos reservados.')
    expect(copyright.className).toBe('mt-8 text-center text-xs')
    expect(copyright.style.color).toBe(cssValue('color', colors2000s.text.disabled))
    // Debajo del copyright cierran la columna los enlaces legales.
    expect(column.lastElementChild).toBe(copyright.nextElementSibling)
    expect(column.lastElementChild?.textContent).toBe('Términos y condiciones·Privacidad')
  })

  const renderReset = () =>
    render(
      <MemoryRouter initialEntries={['/reset-password?token=abc']}>
        <ResetPasswordPage />
      </MemoryRouter>
    )

  const submitWith = (clave: string) => {
    fireEvent.change(screen.getByLabelText('Nueva contraseña'), { target: { value: clave } })
    fireEvent.change(screen.getByLabelText('Confirmar contraseña'), { target: { value: clave } })
    fireEvent.submit(screen.getByRole('button', { name: 'Actualizar contraseña' }).closest('form')!)
  }

  beforeEach(() => {
    mockMutateAsync.mockReset()
  })

  it('rechaza una clave de menos de 6 caracteres sin llamar al backend (L1)', async () => {
    // 2026-10-01, D-20261001-01: el piso era 12 (L1, 2026-09); la decisión del
    // dueño lo bajó a 6, con tope de 64 caracteres y 72 bytes.
    renderReset()

    submitWith('ab12')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'La contraseña debe tener al menos 6 caracteres'
    )
    expect(mockMutateAsync).not.toHaveBeenCalled()
  })

  it('avisa antes de enviar que la clave supera los 72 bytes (36 letras con tilde y un número)', async () => {
    renderReset()

    // 36 x 'é' (72 bytes) + '1' = 73 bytes: son 37 caracteres, pero el backend
    // responde 422 porque bcrypt solo toma 72 bytes.
    submitWith(`${'é'.repeat(36)}1`)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'La contraseña ocupa más de 72 bytes (los acentos, la ñ, los símbolos y los emojis ocupan más de uno)'
    )
    expect(mockMutateAsync).not.toHaveBeenCalled()
  })

  it('pide letra y número como el backend', async () => {
    renderReset()

    submitWith('abcdefgh')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'La contraseña debe incluir al menos un número'
    )
    expect(mockMutateAsync).not.toHaveBeenCalled()
  })

  it('manda la clave tal cual, sin recortar, cuando cumple las reglas', async () => {
    mockMutateAsync.mockResolvedValue({ message: 'ok' })
    renderReset()

    submitWith(' abc123 ')

    await waitFor(() => {
      expect(mockMutateAsync).toHaveBeenCalledWith({ token: 'abc', new_password: ' abc123 ' })
    })
  })

  it('las dos claves son new-password y la nueva lleva los topes 6 y 64', () => {
    renderReset()

    const nueva = screen.getByLabelText('Nueva contraseña')
    expect(nueva).toHaveAttribute('type', 'password')
    expect(nueva).toHaveAttribute('autocomplete', 'new-password')
    expect(nueva).toHaveAttribute('minlength', '6')
    expect(nueva).toHaveAttribute('maxlength', '128')

    const confirmar = screen.getByLabelText('Confirmar contraseña')
    expect(confirmar).toHaveAttribute('type', 'password')
    expect(confirmar).toHaveAttribute('autocomplete', 'new-password')
    expect(confirmar).toHaveAttribute('maxlength', '128')
  })

  it('un 422 del servidor (clave común) muestra un texto útil, no el genérico', async () => {
    mockMutateAsync.mockRejectedValue(
      new ValidationError('body -> new_password: value error', {
        errorCode: 'VALIDATION_ERROR',
        statusCode: 422
      })
    )
    renderReset()

    submitWith('password123')

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'La contraseña no es aceptable: es demasiado común o no cumple las reglas. Elegí otra'
    )
  })
})
