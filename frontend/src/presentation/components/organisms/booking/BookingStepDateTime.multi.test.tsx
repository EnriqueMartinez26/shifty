import { fireEvent, render, screen } from '@testing-library/react'

import { ValidationError } from '@shared/errors'
import { formatArgentinaDate } from '@shared/utils/argentinaTime'

import { BookingStepDateTime } from './BookingStepDateTime'

// Varios servicios en un turno (2026-10-16): la grilla mide el turno entero y
// solo ofrece a quien hace todos los servicios.

const mockAvailability = jest.fn()
const mockStaff = jest.fn()
const bookingDate = formatArgentinaDate(new Date().toISOString())

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
      selectedDate={bookingDate}
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

    expect(mockAvailability).toHaveBeenCalledWith('store-1', 'corte', bookingDate, false, ['barba'])
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

  // Revision de #194 (M2): un 422 de la grilla se explica, no se muestra vacia.
  it('un 422 de la grilla dice por que y deja reintentar', () => {
    const refetch = jest.fn()
    mockStaff.mockReturnValue({ data: [profesional('ana', ['corte', 'barba'])], isLoading: false })
    mockAvailability.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new ValidationError('rechazado', {
        errorCode: 'MULTI_SERVICE_DISABLED',
        statusCode: 422
      }),
      refetch
    })
    renderPaso(['barba'])

    expect(screen.getByRole('alert')).toHaveTextContent(
      'La tienda ya no toma varios servicios en un mismo turno.'
    )
    expect(screen.queryByText('No hay turnos disponibles.')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }))
    expect(refetch).toHaveBeenCalled()
  })
})
