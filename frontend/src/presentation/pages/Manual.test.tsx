import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import Manual from './Manual'

const renderManual = () =>
  render(
    <MemoryRouter>
      <Manual />
    </MemoryRouter>
  )

describe('Manual', () => {
  it('names the section navigation and links the selected tab to its heading', () => {
    renderManual()

    const tablist = screen.getByRole('tablist', { name: 'Secciones del manual' })
    const selectedTab = within(tablist).getByRole('tab', { name: 'Primeros pasos' })
    const panel = screen.getByRole('tabpanel')
    within(panel).getByRole('heading', { level: 2, name: 'Primeros pasos' })

    within(tablist)
      .getAllByRole('tab')
      .forEach((tab) => {
        const controlledPanelId = tab.getAttribute('aria-controls')
        expect(controlledPanelId).toBeTruthy()
        expect(document.getElementById(controlledPanelId ?? '')).toBeInTheDocument()
      })

    expect(selectedTab).toHaveAttribute('aria-selected', 'true')
    expect(selectedTab).toHaveAttribute('aria-controls', panel.id)
    expect(panel).toHaveAttribute('aria-labelledby', selectedTab.id)
  })

  it('selects the requested section and exposes its active panel', () => {
    renderManual()

    const tab = screen.getByRole('tab', { name: 'Cobrar señas con Mercado Pago' })
    fireEvent.click(tab)

    const panel = screen.getByRole('tabpanel')
    within(panel).getByRole('heading', {
      level: 2,
      name: 'Cobrar señas con Mercado Pago'
    })

    expect(tab).toHaveAttribute('aria-selected', 'true')
    expect(tab).toHaveAttribute('aria-controls', panel.id)
    expect(panel).toHaveAttribute('aria-labelledby', tab.id)
    expect(screen.getByRole('tab', { name: 'Primeros pasos' })).toHaveAttribute(
      'aria-selected',
      'false'
    )
  })

  it('supports arrow, Home and End keyboard navigation between sections', () => {
    renderManual()

    const firstTab = screen.getByRole('tab', { name: 'Primeros pasos' })
    firstTab.focus()
    fireEvent.keyDown(firstTab, { key: 'ArrowRight' })

    const agendaTab = screen.getByRole('tab', { name: 'Tu agenda día a día' })
    expect(agendaTab).toHaveFocus()
    expect(agendaTab).toHaveAttribute('aria-selected', 'true')

    fireEvent.keyDown(agendaTab, { key: 'End' })
    const lastTab = screen.getByRole('tab', { name: 'Promociones y reportes' })
    expect(lastTab).toHaveFocus()
    expect(lastTab).toHaveAttribute('aria-selected', 'true')

    fireEvent.keyDown(lastTab, { key: 'Home' })
    expect(firstTab).toHaveFocus()
    expect(firstTab).toHaveAttribute('aria-selected', 'true')
  })

  it('gives section controls and legal links 44 px targets and visible orange focus', () => {
    renderManual()

    const controls = [
      ...screen.getAllByRole('tab'),
      screen.getByRole('link', { name: 'Términos y condiciones' }),
      screen.getByRole('link', { name: 'Privacidad' })
    ]

    controls.forEach((control) => {
      expect(control).toHaveClass('min-h-11')
      expect(control).toHaveClass('focus-visible:outline-[#9a4507]')
    })
  })

  // S6 antiabuso (2026-10-22): la limpieza de reservas del portal se explica
  // junto a la agenda, donde vive el resto del trabajo sobre turnos.
  it('explica como cancelar reservas sospechosas del portal', () => {
    renderManual()

    fireEvent.click(screen.getByRole('tab', { name: 'Tu agenda día a día' }))

    const panel = screen.getByRole('tabpanel')
    within(panel).getByRole('heading', { name: 'Limpiar reservas sospechosas del portal' })
    expect(panel).toHaveTextContent('Reservas del portal')
  })
})
