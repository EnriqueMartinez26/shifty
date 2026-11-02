import { fireEvent, render, screen, within } from '@testing-library/react'

import { AgendaDayView } from './AgendaDayView'
import type { DayGrid } from '../../../lib/calendarGrid'
import { AppointmentActions } from '../../molecules/AppointmentActions'
import { ClientWhatsAppButton } from '../../molecules/ClientWhatsAppButton'

// 2026-09-30: la vista dia salio de CalendarContainer (F11c-08). Solo pinta:
// abrir un hueco, editar un bloqueo y los controles de cada turno los decide
// el contenedor.

const dayGrid: DayGrid = {
  totalHeightPx: 300,
  bands: [
    {
      kind: 'open',
      startMinutes: 540,
      endMinutes: 600,
      topPx: 0,
      heightPx: 256,
      labels: [{ text: '09:00', topPx: 0 }]
    },
    {
      kind: 'closed',
      key: 'gap-600',
      startMinutes: 600,
      endMinutes: 840,
      topPx: 256,
      heightPx: 44,
      label: '10:00 - 14:00',
      expanded: false
    }
  ]
}

const staffMembers = [
  { id: 'st-1', displayName: 'Ana Gomez' },
  { id: 'st-2', displayName: 'Bruno Diaz' }
]

const block = {
  public_id: 'blk-1',
  staff_id: 'st-1',
  starts_at: '2026-09-15T12:00:00.000Z',
  ends_at: '2026-09-15T12:30:00.000Z',
  reason: 'Almuerzo'
}

const card = {
  id: 'apt-1',
  type: 'appointment' as const,
  staffId: 'st-2',
  staffName: 'Bruno Diaz',
  title: 'Carla Ruiz',
  subtitle: 'Corte',
  startsAt: new Date('2026-09-15T12:00:00Z'),
  endsAt: new Date('2026-09-15T12:30:00Z'),
  status: 'confirmed',
  clientPhone: null,
  clientHasEmail: true,
  serviceId: 'svc-1',
  top: '0px',
  height: '128px',
  timeLabel: '09:00'
}

const renderDayView = (loading = false) => {
  const handlers = {
    onToggleGap: jest.fn(),
    onEditBlock: jest.fn(),
    renderControls: jest.fn(() => <button type="button">Confirmar</button>)
  }
  render(
    <AgendaDayView
      staffMembers={staffMembers}
      loading={loading}
      dayGrid={dayGrid}
      hoursOfDay={{ byStaff: new Map([['st-1', null]]) }}
      blocks={[block]}
      cards={[card]}
      canManageBlocks={false}
      {...handlers}
    />
  )
  return handlers
}

describe('AgendaDayView', () => {
  it('pinta un encabezado por profesional con sus iniciales y la grilla', () => {
    renderDayView()
    expect(screen.getByText('AG')).toBeInTheDocument()
    expect(screen.getByText('Bruno Diaz', { selector: 'p' })).toBeInTheDocument()
    expect(screen.getByText('09:00', { selector: 'span' })).toBeInTheDocument()
    expect(screen.getByText('Carla Ruiz')).toBeInTheDocument()
    // QA 2026-10-02: el estado salia crudo ('CONFIRMED' con uppercase).
    expect(screen.getByText('09:00 - Confirmado')).toBeInTheDocument()
    expect(screen.queryByText('Actualizando agenda...')).not.toBeInTheDocument()
  })

  it('arma los controles de cada turno con renderControls', () => {
    const handlers = renderDayView()
    expect(handlers.renderControls).toHaveBeenCalledWith(card)
    expect(screen.getByRole('button', { name: 'Confirmar' })).toBeInTheDocument()
  })

  it('avisa el hueco cerrado por callback', () => {
    const handlers = renderDayView()
    const gap = screen.getByTitle('Cerrado 10:00 - 14:00')
    expect(gap).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(gap)
    expect(handlers.onToggleGap).toHaveBeenCalledWith('gap-600')
  })

  it('muestra el aviso de carga', () => {
    renderDayView(true)
    expect(screen.getByText('Cargando profesionales...')).toBeInTheDocument()
  })

  // QA movil 2026-10-08: en el dia, los iconos tapaban el nombre del servicio
  // y la grilla de 800 px con varios profesionales no se podia recorrer.
  it('los controles del turno van debajo del nombre, no encima', () => {
    renderDayView()
    const controls = screen.getByRole('button', { name: 'Confirmar' }).parentElement
    expect(controls).not.toHaveClass('absolute')
    expect(
      precedesNode(
        screen.getByText('Carla Ruiz'),
        screen.getByRole('button', { name: 'Confirmar' })
      )
    ).toBe(true)
  })

  // Revision de la PR #129: con alto fijo y overflow-y-auto, un turno corto
  // (piso de 30 min = 128 px) dejaba las acciones de 40x40 adentro de un
  // scroll anidado diminuto en el telefono.
  it('la tarjeta crece hasta mostrar sus acciones, sin scroll propio', () => {
    renderDayView()
    const tarjeta = screen.getByText('Carla Ruiz').closest('[data-appointment-card]')
    expect(tarjeta).not.toBeNull()
    const estilo = (tarjeta as HTMLElement).style

    expect(estilo.minHeight).toBe(card.height)
    expect(estilo.height).toBe('')
    expect(tarjeta).not.toHaveClass('overflow-y-auto', 'overflow-auto', 'overflow-hidden')
    // Si al crecer tapa al turno de abajo, tocarla la trae al frente.
    expect(tarjeta).toHaveClass('focus-within:z-20', 'hover:z-20')
  })

  // Produccion 2026-10-14: en la vista dia de escritorio, Cancelar, Reprogramar
  // y WhatsApp no hacian nada. Con un solo profesional la tarjeta mide ~1000 px
  // y `active:scale-95` la achicaba hacia el centro al apretar: el boton se
  // corria ~25 px, el mouseup caia afuera y el navegador no disparaba el
  // click. jsdom no mide transformaciones, asi que se fijan las clases.
  it('la tarjeta del turno no se escala al pasar ni al apretar', () => {
    renderDayView()
    const tarjeta = screen.getByText('Carla Ruiz').closest('[data-appointment-card]')
    expect(tarjeta).not.toBeNull()
    expect(scaleClasses(tarjeta as HTMLElement)).toEqual([])
    // Sigue marcando la tarjeta activa sin moverla.
    expect(tarjeta).toHaveClass('hover:outline-2', 'focus-within:outline-2')
  })

  it('Cancelar, Reprogramar y WhatsApp de la tarjeta reciben el click', () => {
    const onAction = jest.fn()
    render(
      <AgendaDayView
        staffMembers={staffMembers}
        loading={false}
        dayGrid={dayGrid}
        hoursOfDay={{ byStaff: new Map() }}
        blocks={[]}
        cards={[card]}
        canManageBlocks={false}
        onToggleGap={jest.fn()}
        onEditBlock={jest.fn()}
        renderControls={(event) => (
          <>
            <AppointmentActions
              status={event.status}
              hasStarted={false}
              canRelease={false}
              canManage
              canCancelOrReschedule
              busy={false}
              compact
              onAction={onAction}
            />
            <ClientWhatsAppButton
              phone="+5491155550031"
              status={event.status}
              compact
              message={whatsAppMessage}
            />
          </>
        )}
      />
    )
    const tarjeta = screen.getByText('Carla Ruiz').closest('[data-appointment-card]') as HTMLElement

    fireEvent.click(within(tarjeta).getByRole('button', { name: 'Cancelar turno' }))
    fireEvent.click(within(tarjeta).getByRole('button', { name: 'Reprogramar turno' }))
    expect(onAction.mock.calls).toEqual([['cancel'], ['reschedule']])

    const whatsApp = within(tarjeta).getByRole('link', { name: 'Recordar por WhatsApp' })
    const onWhatsAppClick = jest.fn((event: MouseEvent) => event.preventDefault())
    whatsApp.addEventListener('click', onWhatsAppClick)
    fireEvent.click(whatsApp)
    expect(onWhatsAppClick).toHaveBeenCalledTimes(1)
  })

  it('expone las regiones de desplazamiento de la grilla larga para teclado y lector de pantalla', () => {
    render(
      <AgendaDayView
        staffMembers={staffMembers}
        loading={false}
        dayGrid={{ ...dayGrid, totalHeightPx: 900 }}
        hoursOfDay={{ byStaff: new Map() }}
        blocks={[]}
        cards={[]}
        canManageBlocks={false}
        onToggleGap={jest.fn()}
        onEditBlock={jest.fn()}
        renderControls={() => null}
      />
    )

    const horizontalRegion = screen.getByRole('region', {
      name: 'Agenda diaria por profesional, desplazable horizontalmente'
    })
    const verticalRegion = screen.getByRole('region', {
      name: 'Horarios de la agenda diaria, desplazable verticalmente'
    })

    expect(horizontalRegion).toHaveAttribute('tabindex', '0')
    expect(verticalRegion).toHaveAttribute('tabindex', '0')
    expect(verticalRegion).toHaveAttribute('aria-describedby', 'agenda-day-scroll-hint')
    expect(
      screen.getByText('Deslizá verticalmente para recorrer los horarios.')
    ).toBeInTheDocument()
    expect(screen.getByText('Ana Gomez', { selector: 'p' })).toBeInTheDocument()
    expect(screen.getByText('Bruno Diaz', { selector: 'p' })).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: 'Profesional' })).not.toBeInTheDocument()
  })

  it('la grilla solo exige 800 px de ancho desde tablet', () => {
    const { container } = render(
      <AgendaDayView
        staffMembers={staffMembers}
        loading={false}
        dayGrid={dayGrid}
        hoursOfDay={{ byStaff: new Map() }}
        blocks={[]}
        cards={[]}
        canManageBlocks={false}
        onToggleGap={jest.fn()}
        onEditBlock={jest.fn()}
        renderControls={() => null}
      />
    )
    expect(container.querySelector('[class~="min-w-[800px]"]')).toBeNull()
    expect(container.querySelector('[class~="md:min-w-[800px]"]')).not.toBeNull()
  })
})

const whatsAppMessage = {
  clientName: 'Carla Ruiz',
  serviceName: 'Corte',
  staffName: 'Bruno Diaz',
  startsAt: card.startsAt,
  storeName: 'Sol',
  rebookUrl: null
}

/** Clases de Tailwind que escalan el elemento, con o sin variante. */
const scaleClasses = (element: HTMLElement) =>
  Array.from(element.classList).filter((name) => /(^|:)-?scale-/.test(name))

/** `a` aparece antes que `b` en el documento. */
const precedesNode = (a: HTMLElement, b: HTMLElement) =>
  Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)
