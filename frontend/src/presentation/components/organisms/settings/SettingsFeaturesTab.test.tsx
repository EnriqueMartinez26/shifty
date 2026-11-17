import { fireEvent, render, screen } from '@testing-library/react'

import type { StoreFeatureFlags } from '@application/services/StoreSettingsService'

import { SettingsFeaturesTab } from './SettingsFeaturesTab'

// 2026-10-02: la pestana de funciones salio de Settings.tsx (F11b-08). Devuelve
// los flags completos con el tocado invertido; los ocultos viajan sin cambios.

const flags: StoreFeatureFlags = {
  payments: false,
  ledger: true,
  advanced_reports: true,
  new_calendar: false,
  otp_booking: false,
  multi_service_booking: false,
  suggested_slots_only: false
}

describe('SettingsFeaturesTab', () => {
  it('muestra solo los cinco flags que el backend lee', () => {
    render(<SettingsFeaturesTab flags={flags} onChange={jest.fn()} />)

    expect(screen.getAllByRole('switch')).toHaveLength(5)
    expect(screen.getByRole('switch', { name: 'Deuda / fiado' })).toHaveAttribute(
      'aria-checked',
      'true'
    )
  })

  it('el interruptor devuelve los flags con ese invertido', () => {
    const onChange = jest.fn()
    render(<SettingsFeaturesTab flags={flags} onChange={onChange} />)

    fireEvent.click(screen.getByRole('switch', { name: 'Cobros online y señas' }))

    expect(onChange).toHaveBeenCalledWith({ ...flags, payments: true })
  })

  // 2026-10-16: varios servicios en un turno, apagado por defecto.
  it('varios servicios en un turno se prende desde aca y explica que hace', () => {
    const onChange = jest.fn()
    render(<SettingsFeaturesTab flags={flags} onChange={onChange} />)

    expect(screen.getByText(/hasta 3 servicios que hace el mismo profesional/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('switch', { name: 'Varios servicios en un turno' }))

    expect(onChange).toHaveBeenCalledWith({ ...flags, multi_service_booking: true })
  })

  // 2026-11-17 (decision de Mateo): saca "Ver todos" de la reserva publica.
  it('solo horarios sugeridos se prende desde aca y explica que hace', () => {
    const onChange = jest.fn()
    render(<SettingsFeaturesTab flags={flags} onChange={onChange} />)

    expect(screen.getByText(/se oculta la opción "Ver todos"/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('switch', { name: 'Solo horarios sugeridos' }))

    expect(onChange).toHaveBeenCalledWith({ ...flags, suggested_slots_only: true })
  })

  it('en solo lectura los interruptores se apagan con el motivo', () => {
    const onChange = jest.fn()
    render(
      <SettingsFeaturesTab flags={flags} onChange={onChange} readOnlyReason="Tienda suspendida" />
    )

    for (const toggle of screen.getAllByRole('switch')) {
      expect(toggle).toBeDisabled()
      expect(toggle).toHaveAttribute('title', 'Tienda suspendida')
    }
    fireEvent.click(screen.getByRole('switch', { name: 'Deuda / fiado' }))
    expect(onChange).not.toHaveBeenCalled()
  })
})
