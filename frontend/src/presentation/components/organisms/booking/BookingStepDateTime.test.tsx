import { fireEvent, render, screen } from '@testing-library/react'
import { format } from 'date-fns'

import { BookingStepDateTime } from './BookingStepDateTime'

const mockAvailability = jest.fn()
const mockStaff = jest.fn()

jest.mock('@presentation/hooks/usePublic', () => ({
  usePublicAvailability: (...args: unknown[]) => mockAvailability(...args),
  usePublicStaff: (...args: unknown[]) => mockStaff(...args),
  useJoinWaitlist: () => ({ mutateAsync: jest.fn(), isPending: false, isSuccess: false })
}))

describe('BookingStepDateTime', () => {
  beforeEach(() => {
    mockAvailability.mockReset()
    mockStaff.mockReset()
    mockStaff.mockReturnValue({ data: [], isLoading: false })
  })

  it('muestra los slots en hora argentina y entrega el instante UTC al elegir', () => {
    // Regresion 2026-09-10: se mostraba la hora UTC del slot ("00:00" para un
    // turno de 21:00) y al reservar se recomponia fecha local + esa hora, con lo
    // que el turno caia en el dia anterior.
    mockAvailability.mockReturnValue({
      isLoading: false,
      data: [
        {
          staff_id: 'st-1',
          staff_name: 'Pro',
          starts_at: '2026-09-15T12:00:00+00:00',
          ends_at: '2026-09-15T12:30:00+00:00',
          status: 'available',
          reason: null
        },
        {
          staff_id: 'st-1',
          staff_name: 'Pro',
          starts_at: '2026-09-16T00:00:00+00:00',
          ends_at: '2026-09-16T00:30:00+00:00',
          status: 'available',
          reason: null
        }
      ]
    })
    const onSelect = jest.fn()

    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId="st-1"
        selectedDate={null}
        selectedTime={null}
        onSelect={onSelect}
        onBack={() => undefined}
      />
    )

    expect(screen.getByText('09:00')).toBeInTheDocument()
    expect(screen.getByText('21:00')).toBeInTheDocument()
    expect(screen.queryByText('00:00')).not.toBeInTheDocument()
    expect(screen.queryByText('12:00')).not.toBeInTheDocument()

    fireEvent.click(screen.getByText('21:00'))

    expect(onSelect).toHaveBeenCalledTimes(1)
    const [, hora, staff, , startsAt] = onSelect.mock.calls[0] as [
      string,
      string,
      string,
      string | null,
      string
    ]
    expect(hora).toBe('21:00')
    expect(staff).toBe('st-1')
    expect(startsAt).toBe('2026-09-16T00:00:00+00:00')
  })

  it('con "cualquier profesional" agrupa por hora argentina y prefiere el slot disponible', () => {
    mockAvailability.mockReturnValue({
      isLoading: false,
      data: [
        {
          staff_id: 'st-1',
          staff_name: 'Ana',
          starts_at: '2026-09-15T12:00:00+00:00',
          ends_at: '2026-09-15T12:30:00+00:00',
          status: 'booked',
          reason: null
        },
        {
          staff_id: 'st-2',
          staff_name: 'Bruno',
          starts_at: '2026-09-15T12:00:00+00:00',
          ends_at: '2026-09-15T12:30:00+00:00',
          status: 'available',
          reason: null
        }
      ]
    })

    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId={null}
        selectedDate={null}
        selectedTime={null}
        onSelect={() => undefined}
        onBack={() => undefined}
      />
    )

    expect(screen.getAllByText('09:00')).toHaveLength(1)
    expect(screen.getByText('Bruno')).toBeInTheDocument()
    expect(screen.queryByText('Ana')).not.toBeInTheDocument()
  })

  it('con recursos (cancha, sala) no habla de "profesional"', () => {
    mockAvailability.mockReturnValue({ isLoading: false, data: [] })
    mockStaff.mockReturnValue({
      isLoading: false,
      data: [
        {
          public_id: 'cancha-1',
          kind: 'resource',
          first_name: '',
          last_name: '',
          display_name: 'Cancha 1',
          service_ids: ['svc-1']
        }
      ]
    })

    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId={null}
        selectedDate={null}
        selectedTime={null}
        onSelect={() => undefined}
        onBack={() => undefined}
      />
    )

    expect(screen.getByText('Cancha / sala')).toBeInTheDocument()
    expect(screen.getByText('Cancha 1')).toBeInTheDocument()
    expect(
      screen.getByText('Te mostramos horarios en cualquier cancha o sala disponible.')
    ).toBeInTheDocument()
    expect(screen.queryByText(/profesional/i)).not.toBeInTheDocument()
  })

  it('"Ver todos" es un interruptor alcanzable y operable por teclado', () => {
    // F11a-09 (2026-09-24): era un div con onClick dentro de un label sin
    // control: Tab no llegaba y Enter/Espacio no hacian nada. Un <button> nativo
    // recibe foco y el navegador lo activa con Enter/Espacio (jsdom no simula
    // esa activacion, asi que se verifica el elemento y su efecto).
    mockAvailability.mockReturnValue({ isLoading: false, data: [] })

    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId={null}
        selectedDate="2026-09-25"
        selectedTime={null}
        onSelect={() => undefined}
        onBack={() => undefined}
      />
    )

    const interruptor = screen.getByRole('switch', { name: /ver todos/i })
    expect(interruptor.tagName).toBe('BUTTON')
    expect(interruptor).toHaveAttribute('type', 'button')
    expect(interruptor).toHaveAttribute('aria-checked', 'false')

    interruptor.focus()
    expect(interruptor).toHaveFocus()

    fireEvent.click(interruptor)

    expect(interruptor).toHaveAttribute('aria-checked', 'true')
    expect(mockAvailability).toHaveBeenLastCalledWith('store-1', 'svc-1', '2026-09-25', true)
  })

  it('una fecha lejana que vino por deep-link aparece en la tira y carga sus horarios', () => {
    // La tira muestra 14 dias: el ?date= de un link de reoferta a 45 dias
    // cargaba sus horarios pero el dia no se veia seleccionado en ningun lado.
    mockAvailability.mockReturnValue({ isLoading: false, data: [] })
    const lejana = new Date()
    lejana.setDate(lejana.getDate() + 45)
    const lejanaStr = format(lejana, 'yyyy-MM-dd')

    render(
      <BookingStepDateTime
        storePublicId="store-1"
        serviceId="svc-1"
        staffId={null}
        selectedDate={lejanaStr}
        selectedTime={null}
        onSelect={() => undefined}
        onBack={() => undefined}
      />
    )

    expect(screen.getByTestId(`date-${lejanaStr}`)).toBeInTheDocument()
    expect(mockAvailability).toHaveBeenCalledWith('store-1', 'svc-1', lejanaStr, false)
  })
})
