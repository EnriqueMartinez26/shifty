import { mdiStore } from '@mdi/js'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import ResetPasswordPage from './ResetPassword'
import { colors2000s } from '../../theme/colors'

/** The value as jsdom normalizes it (hex to rgb), so it can be compared with `element.style`. */
const cssValue = (property: 'color' | 'border' | 'borderTop', value: string): string => {
  const probe = document.createElement('div')
  probe.style[property] = value
  return probe.style[property]
}

const mockMutateAsync = jest.fn()

jest.mock('../hooks/useResetPassword', () => ({
  useResetPassword: () => ({
    mutateAsync: mockMutateAsync,
    isPending: false
  })
}))

describe('ResetPasswordPage', () => {
  // F11b-14: pins the page shell before it moves to `AuthShell`.
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
    expect(column.lastElementChild).toBe(copyright)
  })

  it('rechaza una clave de menos de 12 caracteres sin llamar al backend (L1)', async () => {
    // El backend exige 12 (`ResetPasswordRequest`); con el piso viejo de 8,
    // una clave de 10 pasaba el formulario y volvia como 422.
    render(
      <MemoryRouter initialEntries={['/reset-password?token=abc']}>
        <ResetPasswordPage />
      </MemoryRouter>
    )

    fireEvent.change(screen.getByLabelText('Nueva contraseña'), {
      target: { value: 'corta12345' }
    })
    fireEvent.change(screen.getByLabelText('Confirmar contraseña'), {
      target: { value: 'corta12345' }
    })
    fireEvent.submit(screen.getByRole('button', { name: 'Actualizar contraseña' }).closest('form')!)

    expect(await screen.findByRole('alert')).toHaveTextContent('al menos 12 caracteres')
    expect(mockMutateAsync).not.toHaveBeenCalled()
  })
})
