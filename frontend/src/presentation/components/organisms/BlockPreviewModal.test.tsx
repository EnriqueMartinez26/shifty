import { fireEvent, render, screen } from '@testing-library/react'

import type { BlockPreviewResult } from '@application/services/AppointmentBlocksService'

import { BlockPreviewModal, buildWhatsAppText } from './BlockPreviewModal'

const preview: BlockPreviewResult = {
  ranges: 2,
  affected: [
    {
      public_id: 'a1',
      client_name: 'Carla Ruiz',
      client_phone: '+54 9 11 5555-0001',
      service_name: 'Consulta',
      staff_name: 'Ana',
      starts_at: '2026-09-15T13:00:00+00:00',
      ends_at: '2026-09-15T13:30:00+00:00',
      status: 'confirmed',
      blocker: null,
      cancellable: true
    },
    {
      public_id: 'a2',
      client_name: 'Bruno',
      client_phone: null,
      service_name: 'Consulta',
      staff_name: 'Ana',
      starts_at: '2026-09-16T00:00:00+00:00',
      ends_at: '2026-09-16T00:30:00+00:00',
      status: 'pending_payment',
      blocker: 'pending_payment',
      cancellable: false
    }
  ]
}

describe('BlockPreviewModal', () => {
  it('lista los afectados en hora argentina y separa los que requieren decision', () => {
    render(
      <BlockPreviewModal
        preview={preview}
        reason="Vacaciones"
        busy={false}
        canCancel
        onConfirm={() => undefined}
        onCancel={() => undefined}
      />
    )
    expect(screen.getByText('Hay 2 turnos dentro del bloqueo')).toBeInTheDocument()
    expect(
      screen.getAllByText((_, el) => el?.textContent?.includes('15/09/2026 10:00 hs') ?? false)
        .length
    ).toBeGreaterThan(0)
    expect(
      screen.getAllByText((_, el) => (el?.textContent ?? '').includes('21:00 hs')).length
    ).toBeGreaterThan(0)
    expect(screen.getByText(/Esperando la seña/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Cancelar 1 turno y bloquear' })).toBeInTheDocument()
  })

  // 2026-10-02, QA en navegador: un telefono ilegible armaba un wa.me roto.
  it('un telefono que no se puede leer no ofrece WhatsApp', () => {
    const [primero] = preview.affected
    render(
      <BlockPreviewModal
        preview={{ ...preview, affected: [{ ...primero!, client_phone: '123' }] }}
        reason="Vacaciones"
        busy={false}
        canCancel
        onConfirm={() => undefined}
        onCancel={() => undefined}
      />
    )
    expect(screen.queryByText(/Avisar por WhatsApp/)).not.toBeInTheDocument()
  })

  it('el link de WhatsApp lleva el telefono sin simbolos y el texto armado', () => {
    render(
      <BlockPreviewModal
        preview={preview}
        reason="Vacaciones"
        busy={false}
        canCancel
        onConfirm={() => undefined}
        onCancel={() => undefined}
      />
    )
    const links = screen.getAllByRole('link', { name: /Avisar por WhatsApp/ })
    expect(links).toHaveLength(1)
    const href = links[0]?.getAttribute('href') ?? ''
    expect(href.startsWith('https://wa.me/5491155550001?text=')).toBe(true)
    expect(decodeURIComponent(href)).toContain('Vacaciones')
    expect(buildWhatsAppText(preview.affected[0]!, 'Vacaciones')).toContain('10:00')
  })

  it('confirmar y volver disparan sus callbacks', () => {
    const onConfirm = jest.fn()
    const onCancel = jest.fn()
    render(
      <BlockPreviewModal
        preview={preview}
        reason="Vacaciones"
        busy={false}
        canCancel
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar 1 turno y bloquear' }))
    fireEvent.click(screen.getByRole('button', { name: 'Volver' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)
    expect(onCancel).toHaveBeenCalledTimes(1)
  })

  // FF-34: el backend responde 403 a quien no es administrador cuando hay
  // turnos afectados; ofrecerle "Cancelar y bloquear" era un boton a un error.
  it('sin permiso de cancelar muestra la lista y solo deja volver', () => {
    const onCancel = jest.fn()
    render(
      <BlockPreviewModal
        preview={preview}
        reason="Vacaciones"
        busy={false}
        canCancel={false}
        onConfirm={() => undefined}
        onCancel={onCancel}
      />
    )
    expect(screen.getByText('Carla Ruiz')).toBeInTheDocument()
    expect(screen.getByText(/Pedile a un administrador que confirme/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /bloquear/i })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Volver' }))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })
})
