import { fireEvent, render, screen } from '@testing-library/react'

import { SettingsPoliciesTab } from './SettingsPoliciesTab'

// 2026-10-02: la pestana de politicas salio de Settings.tsx (F11b-08). Cada
// campo devuelve solo su clave, ya recortada a su tope.

const value = {
  cancellation_hours: 24,
  buffer_minutes: 10,
  min_booking_notice_hours: 2,
  deposit_far_notice_days: 0,
  deposit_far_notice_extra_percent: 0,
  deposit_new_client_extra_percent: 0,
  deposit_absent_client_extra_percent: 0
}

describe('SettingsPoliciesTab', () => {
  it('cancelacion y antelacion devuelven solo su campo', () => {
    const onChange = jest.fn()
    render(<SettingsPoliciesTab value={value} onChange={onChange} />)

    fireEvent.change(screen.getByPlaceholderText('24'), { target: { value: '48' } })
    fireEvent.change(screen.getByPlaceholderText('2'), { target: { value: '500' } })

    expect(onChange).toHaveBeenNthCalledWith(1, { cancellation_hours: 48 })
    expect(onChange).toHaveBeenNthCalledWith(2, { min_booking_notice_hours: 168 })
  })

  it('una regla de sena devuelve su clave recortada a 100', () => {
    const onChange = jest.fn()
    render(<SettingsPoliciesTab value={value} onChange={onChange} />)

    fireEvent.change(screen.getByLabelText('Recargo por ausencias (%)'), {
      target: { value: '150' }
    })

    expect(onChange).toHaveBeenCalledWith({ deposit_absent_client_extra_percent: 100 })
  })

  // 2026-10-12: "Sena segun riesgo" se confundia con la politica de sena que
  // exige activar los cobros, y esa se escribe en la pestana Mercado Pago.
  it('aclara que los recargos no son la politica de sena y dice donde se escribe', () => {
    render(<SettingsPoliciesTab value={value} onChange={jest.fn()} />)

    expect(
      screen.getByText(
        'Esto no es tu política de seña: el texto de seña, cancelación y reembolso se escribe en la pestaña Mercado Pago.'
      )
    ).toBeInTheDocument()
  })
})
