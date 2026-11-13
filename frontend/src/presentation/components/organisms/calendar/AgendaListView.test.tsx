import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import { AgendaListView } from './AgendaListView'
import { groupEventsByDay, type UnifiedCalendarEvent } from '../../../lib/calendarEvents'

const eventOf = (id: string, startsAt: string): UnifiedCalendarEvent => ({
  id,
  type: 'block',
  staffId: 'st-1',
  staffName: 'Ana Gomez',
  title: `Evento ${id}`,
  subtitle: 'Bloqueo',
  startsAt: new Date(startsAt),
  endsAt: new Date(startsAt),
  status: 'blocked'
})

const renderEvent = (event: UnifiedCalendarEvent) => <button type="button">{event.title}</button>
const day2 = '2026-10-02'
const day5 = '2026-10-05'
const eventsByDay = () =>
  new Map([
    [day5, [eventOf('c', '2026-10-05T15:00:00Z')]],
    [day2, [eventOf('b', '2026-10-02T18:00:00Z'), eventOf('a', '2026-10-02T12:00:00Z')]]
  ])
const props = () => ({
  eventsByDay: eventsByDay(),
  renderEvent,
  selectedDateKey: day2,
  rangeKey: `${day2}:${day5}`
})
const dayButton = (heading: string) =>
  screen.getByRole('button', { name: new RegExp(heading, 'i') })
const panelFor = (button: HTMLElement) => {
  const id = button.getAttribute('aria-controls')
  expect(id).toBeTruthy()
  const panel = document.getElementById(id!)
  if (!panel) throw new Error('Falta el panel asociado al encabezado')
  expect(panel).toHaveAttribute('role', 'region')
  return panel
}

describe('AgendaListView', () => {
  it('abre el día seleccionado, ordena los eventos y cuenta cada grupo', () => {
    render(<AgendaListView {...props()} />)
    const friday = dayButton('viernes 02/10')
    const monday = dayButton('lunes 05/10')
    expect(friday).toHaveAttribute('aria-expanded', 'true')
    expect(monday).toHaveAttribute('aria-expanded', 'false')
    expect(friday).toHaveTextContent('2 eventos')
    expect(monday).toHaveTextContent('1 evento')
    expect(
      within(panelFor(friday))
        .getAllByRole('button')
        .map((button) => button.textContent)
    ).toEqual(['Evento a', 'Evento b'])
    expect(panelFor(monday)).toHaveClass('hidden')
    expect(friday.querySelector('button')).toBeNull()
  })

  it('abre el primer día con eventos cuando el seleccionado no tiene eventos', () => {
    render(<AgendaListView {...props()} selectedDateKey="2026-10-01" />)
    expect(dayButton('viernes 02/10')).toHaveAttribute('aria-expanded', 'true')
    expect(dayButton('lunes 05/10')).toHaveAttribute('aria-expanded', 'false')
  })

  it('cuenta turnos, ausencias y bloqueos por fecha argentina entre años', () => {
    const block = eventOf('bloqueo', '2027-01-01T02:30:00Z')
    const appointment: UnifiedCalendarEvent = {
      ...eventOf('turno', '2027-01-01T02:45:00Z'),
      type: 'appointment',
      status: 'confirmed',
      clientPhone: null,
      clientHasEmail: false,
      serviceId: 'svc'
    }
    const absence: UnifiedCalendarEvent = {
      ...eventOf('ausencia', '2027-01-01T03:30:00Z'),
      type: 'absence',
      status: 'absent',
      clientPhone: null,
      clientHasEmail: false,
      serviceId: 'svc'
    }
    render(
      <AgendaListView
        eventsByDay={groupEventsByDay([block, appointment, absence])}
        renderEvent={renderEvent}
        selectedDateKey="2026-12-31"
        rangeKey="2026-12-31:2027-01-01"
      />
    )
    const newYearsEve = dayButton('jueves 31/12')
    expect(newYearsEve).toHaveTextContent('2 eventos')
    expect(dayButton('viernes 01/01')).toHaveTextContent('1 evento')
    expect(
      within(panelFor(newYearsEve))
        .getAllByRole('button')
        .map((button) => button.textContent)
    ).toEqual(['Evento bloqueo', 'Evento turno'])
  })

  it('espera la carga asíncrona y conserva el cierre manual ante un refetch', () => {
    const initial = props()
    const { rerender } = render(<AgendaListView {...initial} eventsByDay={new Map()} />)
    expect(screen.getByText('No hay eventos para el rango seleccionado.')).toBeInTheDocument()

    rerender(<AgendaListView {...initial} />)
    const selectedDay = dayButton('viernes 02/10')
    expect(selectedDay).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(selectedDay)
    expect(selectedDay).toHaveAttribute('aria-expanded', 'false')

    rerender(<AgendaListView {...props()} />)
    expect(dayButton('viernes 02/10')).toHaveAttribute('aria-expanded', 'false')
  })

  it('permite un solo grupo abierto y conserva la elección durante los renders', () => {
    const { rerender } = render(<AgendaListView {...props()} />)
    fireEvent.click(dayButton('lunes 05/10'))
    expect(dayButton('viernes 02/10')).toHaveAttribute('aria-expanded', 'false')
    expect(dayButton('lunes 05/10')).toHaveAttribute('aria-expanded', 'true')

    rerender(<AgendaListView {...props()} />)
    expect(dayButton('lunes 05/10')).toHaveAttribute('aria-expanded', 'true')
    expect(panelFor(dayButton('viernes 02/10'))).toHaveClass('hidden')
  })

  it('reinicia la selección al cambiar el rango y recupera el primer día disponible', async () => {
    const { rerender } = render(<AgendaListView {...props()} />)
    fireEvent.click(dayButton('lunes 05/10'))

    rerender(
      <AgendaListView {...props()} eventsByDay={new Map([[day2, eventsByDay().get(day2)!]])} />
    )
    await waitFor(() => expect(dayButton('viernes 02/10')).toHaveAttribute('aria-expanded', 'true'))

    rerender(<AgendaListView {...props()} rangeKey="2026-10-05:2026-10-18" />)
    expect(dayButton('viernes 02/10')).toHaveAttribute('aria-expanded', 'true')
    expect(dayButton('lunes 05/10')).toHaveAttribute('aria-expanded', 'false')
  })

  it('mantiene el cierre manual si el rango queda vacío y luego vuelven los eventos', () => {
    const { rerender } = render(<AgendaListView {...props()} />)
    fireEvent.click(dayButton('viernes 02/10'))
    rerender(<AgendaListView {...props()} eventsByDay={new Map()} />)
    rerender(
      <AgendaListView {...props()} eventsByDay={new Map([[day5, eventsByDay().get(day5)!]])} />
    )
    expect(dayButton('lunes 05/10')).toHaveAttribute('aria-expanded', 'false')
  })

  it('asocia paneles únicos por instancia y deja enfocar el encabezado', () => {
    render(
      <>
        <AgendaListView {...props()} />
        <AgendaListView {...props()} />
      </>
    )
    const buttons = screen.getAllByRole('button', { name: /viernes 02\/10/i })
    expect(buttons).toHaveLength(2)
    const [first, second] = buttons
    if (!first || !second) throw new Error('Faltan los encabezados')
    expect(first.getAttribute('aria-controls')).not.toEqual(second.getAttribute('aria-controls'))
    expect(first.querySelector('button')).toBeNull()
    expect(first.getAttribute('aria-controls')).toBeTruthy()
    first.focus()
    expect(first).toHaveFocus()
  })

  it('muestra un mensaje cuando no hay eventos', () => {
    render(
      <AgendaListView
        eventsByDay={new Map()}
        selectedDateKey={day2}
        rangeKey={day2}
        renderEvent={renderEvent}
      />
    )
    expect(screen.getByText('No hay eventos para el rango seleccionado.')).toBeInTheDocument()
  })
})
