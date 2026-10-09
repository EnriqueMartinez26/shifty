import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { toast } from 'sonner'

import { NetworkError } from '@shared/errors'

import NotificationsBell from './NotificationsBell'

/**
 * 2026-09-28 (FF-17). "Marcar todas" y marcar una sola descartaban la promesa
 * con `void`: si fallaba, la campana quedaba igual y nadie decia nada.
 */
jest.mock('sonner', () => ({ toast: { error: jest.fn(), warning: jest.fn(), info: jest.fn() } }))

const mockMarkOne = jest.fn()
const mockMarkAll = jest.fn()
jest.mock('../../hooks/useNotifications', () => ({
  useNotifications: () => ({
    data: {
      unread_count: 1,
      items: [
        {
          public_id: 'ntf-1',
          title: 'Nuevo turno',
          body: null,
          read_at: null,
          created_at: '2026-09-28T12:00:00Z'
        }
      ]
    }
  }),
  useMarkNotificationRead: () => ({ mutateAsync: mockMarkOne, isPending: false }),
  useMarkAllNotificationsRead: () => ({ mutateAsync: mockMarkAll, isPending: false })
}))

const abrir = () => {
  render(<NotificationsBell />)
  fireEvent.click(screen.getByRole('button', { name: /Notificaciones/ }))
}

describe('NotificationsBell', () => {
  beforeEach(() => {
    jest.mocked(toast.error).mockClear()
  })

  it('si "Marcar todas" falla, avisa', async () => {
    mockMarkAll.mockRejectedValue(new NetworkError('No se pudo conectar con el servidor.'))
    abrir()

    fireEvent.click(screen.getByRole('button', { name: /Marcar todas/ }))

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith('No se pudo conectar con el servidor.')
    )
  })

  it('si marcar una notificacion falla, avisa con el texto neutro', async () => {
    mockMarkOne.mockRejectedValue(new Error('boom'))
    abrir()

    fireEvent.click(screen.getByRole('button', { name: /Nuevo turno/ }))

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith('No se pudo marcar la notificación como leída.')
    )
    expect(mockMarkOne).toHaveBeenCalledWith('ntf-1')
  })

  // QA movil 2026-10-08 (390 px): la campana queda a la izquierda del
  // encabezado y el panel, anclado a su borde derecho con w-80, abria en
  // left=-262px. En el telefono se ancla al ancho del encabezado.
  it('en el telefono el panel ocupa el ancho del encabezado, no sale de la pantalla', () => {
    const { container } = render(<NotificationsBell />)
    fireEvent.click(screen.getByRole('button', { name: /Notificaciones/ }))

    const panel = screen.getByRole('region', { name: 'Panel de notificaciones' })
    expect(panel).toHaveClass('absolute', 'inset-x-0', 'top-full')
    expect(panel).toHaveClass('md:inset-x-auto', 'md:right-0', 'md:w-80')
    expect(panel).not.toHaveClass('right-0')
    expect(panel).not.toHaveClass('w-80')
    // La raiz no posiciona en el telefono: el ancla es el encabezado.
    expect(container.firstElementChild).not.toHaveClass('relative')
    expect(container.firstElementChild).toHaveClass('md:relative')
  })
})
