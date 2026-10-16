import { render, screen } from '@testing-library/react'

import { BookingStepDateTime } from './BookingStepDateTime'

// Varios servicios en un turno (2026-10-16): la grilla mide el turno entero y
// solo ofrece a quien hace todos los servicios.

const mockAvailability = jest.fn()
const mockStaff = jest.fn()

jest.mock('@presentation/hooks/usePublic', () => ({
  usePublicAvailability: (...args: unknown[]) => mockAvailability(...args),
  usePublicStaff: (...args: unknown[]) => mockStaff(...args),
  useJoinWaitlist: () => ({ mutateAsync: jest.fn(), isPending: false, isSuccess: false })
}))

const profesional = (public_id: string, service_ids: string[]) => ({
  public_id,
  kind: 'person',
  first_name: public_id,
  last_name: '',
  display_name: `Pro ${public_id}`,
  service_ids
})

const renderPaso = (extraServiceIds?: string[]) =>
  render(
    <BookingStepDateTime
      storePublicId="store-1"
      serviceId="corte"
      extraServiceIds={extraServiceIds}
      staffId={null}
      selectedDate="2026-09-25"
      selectedTime={null}
      onSelect={jest.fn()}
      onBack={jest.fn()}
    />
  )

describe('BookingStepDateTime con varios servicios', () => {
  beforeEach(() => {
    mockAvailability.mockReset()
    mockStaff.mockReset()
    // Un dia lleno: sin horarios libres pero con atencion.
    mockAvailability.mockReturnValue({
      isLoading: false,
      data: [
        {
          staff_id: 'ana',
          staff_name: 'Pro ana',
          starts_at: '2026-09-25T12:00:00+00:00',
          ends_at: '2026-09-25T12:45:00+00:00',
          status: 'booked',
          reason: null
        }
      ]
    })
  })

  it('pide la grilla con los servicios sumados', () => {
    mockStaff.mockReturnValue({ data: [profesional('ana', ['corte', 'barba'])], isLoading: false })
    renderPaso(['barba'])

    expect(mockAvailability).toHaveBeenCalledWith('store-1', 'corte', '2026-09-25', false, [
      'barba'
    ])
  })

  it('el selector ofrece solo a quien hace todos; con uno solo no hay "Cualquiera"', () => {
    mockStaff.mockReturnValue({
      data: [profesional('ana', ['corte', 'barba']), profesional('beto', ['corte'])],
      isLoading: false
    })
    renderPaso(['barba'])

    expect(screen.getByText('Pro ana')).toBeInTheDocument()
    expect(screen.queryByText('Pro beto')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Cualquiera/ })).not.toBeInTheDocument()
  })

  it('con varios que hacen todos, ofrece "Cualquiera" y a cada uno', () => {
    mockStaff.mockReturnValue({
      data: [profesional('ana', ['corte', 'barba']), profesional('caro', ['corte', 'barba'])],
      isLoading: false
    })
    renderPaso(['barba'])

    expect(screen.getByRole('button', { name: /Cualquiera/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Pro caro' })).toBeInTheDocument()
  })

  it('un dia lleno no ofrece la lista de espera: es de un solo servicio', () => {
    mockStaff.mockReturnValue({ data: [profesional('ana', ['corte', 'barba'])], isLoading: false })
    renderPaso(['barba'])

    expect(screen.getByText('No hay turnos disponibles.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Avisame si se libera/ })).not.toBeInTheDocument()
  })

  it('con un solo servicio el dia lleno sigue ofreciendo la lista de espera', () => {
    mockStaff.mockReturnValue({ data: [profesional('ana', ['corte'])], isLoading: false })
    renderPaso()

    expect(screen.getByRole('button', { name: /Avisame si se libera/ })).toBeInTheDocument()
  })
})
