import { fireEvent, render, screen } from '@testing-library/react'

import { SettingsScheduleTab } from './SettingsScheduleTab'

// 2026-10-02: la pestana de horarios salio de Settings.tsx (F11b-08). Devuelve
// el horario completo con el dia tocado; el borrador lo arma la pagina.

describe('SettingsScheduleTab', () => {
  const lunes = { mon: [{ open: '09:00', close: '13:00' }] }

  it('abrir un dia cerrado devuelve el horario completo con ese dia de 09 a 18', () => {
    const onChange = jest.fn()
    render(<SettingsScheduleTab businessHours={lunes} onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { name: 'Abrir Martes' }))

    expect(onChange).toHaveBeenCalledWith({
      mon: [{ open: '09:00', close: '13:00' }],
      tue: [{ open: '09:00', close: '18:00' }]
    })
  })

  it('cerrar un dia lo deja sin periodos', () => {
    const onChange = jest.fn()
    render(<SettingsScheduleTab businessHours={lunes} onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { name: 'Cerrar Lunes' }))

    expect(onChange).toHaveBeenCalledWith({ mon: [] })
  })

  it('apertura posterior al cierre muestra el error del dia', () => {
    render(
      <SettingsScheduleTab
        businessHours={{ mon: [{ open: '14:00', close: '13:00' }] }}
        onChange={jest.fn()}
      />
    )

    expect(screen.getByText('La apertura tiene que ser antes del cierre.')).toBeInTheDocument()
  })
})
