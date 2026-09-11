import { fireEvent, render, screen } from '@testing-library/react'

import { BookingStepDateTime } from './BookingStepDateTime'

const mockAvailability = jest.fn()
const mockStaff = jest.fn()

jest.mock('@presentation/hooks/usePublic', () => ({
  usePublicAvailability: (...args: unknown[]) => mockAvailability(...args),
  usePublicStaff: (...args: unknown[]) => mockStaff(...args)
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
})
