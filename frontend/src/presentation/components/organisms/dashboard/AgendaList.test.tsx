import { render, screen } from '@testing-library/react'

import AgendaList from './AgendaList'
import type { AgendaItem } from './types'

// Rama por rama de `AgendaList` (F11b-09): subtitulo y estado son opcionales, y
// la pagina siempre los manda, asi que sin esto nadie fija el caso sin ellos.

const item = (overrides: Partial<AgendaItem> = {}): AgendaItem => ({
  id: 'g1',
  time: '10:30',
  title: 'Lucia Gomez',
  ...overrides
})

const rowOf = (title: string) => screen.getByText(title).parentElement?.parentElement as HTMLElement

describe('AgendaList', () => {
  // QA 2026-10-02: turnos de varios dias bajo un mismo encabezado, sin fecha.
  it('muestra el dia de cada turno arriba de la hora', () => {
    render(
      <AgendaList
        items={[item({ id: 'a', day: '30/09' }), item({ id: 'b', day: '01/10', title: 'Otro' })]}
        emptyText="vacio"
      />
    )

    expect(screen.getByText('30/09')).toBeInTheDocument()
    expect(screen.getByText('01/10')).toBeInTheDocument()
  })

  it('muestra el texto vacio cuando no hay turnos', () => {
    render(<AgendaList items={[]} emptyText="No hay proximos turnos para mostrar." />)

    expect(screen.getByText('No hay proximos turnos para mostrar.')).toBeInTheDocument()
  })

  it('arma la fila con altura 74, relleno 14, fondo blanco al 68% y borde del tono', () => {
    render(<AgendaList items={[item({ tone: 'warning' })]} emptyText="vacio" />)

    const row = rowOf('Lucia Gomez')
    expect(row.style.minHeight).toBe('74px')
    expect(row.style.padding).toBe('14px')
    expect(row.style.background).toBe('rgba(255, 255, 255, 0.68)')
    expect(row.style.border).toBe('1px solid rgba(245, 158, 11, 0.42)')
  })

  it('pinta la hora con el acento y su caja con el fondo del tono', () => {
    render(<AgendaList items={[item({ tone: 'success' })]} emptyText="vacio" />)

    const time = screen.getByText('10:30')
    expect(time.style.color).toBe('rgb(15, 159, 110)')
    expect((time.parentElement as HTMLElement).style.background).toBe('rgba(16, 185, 129, 0.1)')
  })

  it('omite el subtitulo y el estado cuando no vienen', () => {
    render(<AgendaList items={[item()]} emptyText="vacio" />)

    const row = rowOf('Lucia Gomez')
    expect(row.querySelector('small')).toBeNull()
    // Hora, titulo y nada mas: el pastillero de estado no se dibuja.
    expect(row.querySelectorAll('span')).toHaveLength(1)
  })

  it('muestra el subtitulo y el estado con el tono', () => {
    render(
      <AgendaList
        items={[
          item({ subtitle: 'Corte clasico - Martina Paz', status: 'confirmed', tone: 'success' })
        ]}
        emptyText="vacio"
      />
    )

    expect(screen.getByText('Corte clasico - Martina Paz')).toBeInTheDocument()
    const status = screen.getByText('confirmed')
    expect(status.style.color).toBe('rgb(15, 159, 110)')
    expect(status.style.background).toBe('rgba(16, 185, 129, 0.1)')
  })
})
