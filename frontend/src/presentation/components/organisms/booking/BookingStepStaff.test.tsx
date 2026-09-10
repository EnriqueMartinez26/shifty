import { render, screen } from '@testing-library/react'

import { BookingStepStaff } from './BookingStepStaff'

const mockStaff = jest.fn()

jest.mock('@presentation/hooks/usePublic', () => ({
  usePublicStaff: (...args: unknown[]) => mockStaff(...args)
}))

const renderStep = () =>
  render(
    <BookingStepStaff
      storePublicId="store-1"
      serviceId="svc-1"
      selectedId={null}
      onSelect={jest.fn()}
      onBack={jest.fn()}
    />
  )

describe('BookingStepStaff', () => {
  beforeEach(() => {
    mockStaff.mockReset()
  })

  it('para profesionales pregunta quien atiende y muestra nombre y apellido', () => {
    mockStaff.mockReturnValue({
      isLoading: false,
      data: [
        {
          public_id: 'st-1',
          kind: 'person',
          first_name: 'Ana',
          last_name: 'Perez',
          display_name: 'Ana P.',
          service_ids: ['svc-1']
        }
      ]
    })

    renderStep()

    expect(screen.getByText('Quien te atiende?')).toBeInTheDocument()
    expect(screen.getByText('Cualquier profesional')).toBeInTheDocument()
    expect(screen.getByText('Ana P.')).toBeInTheDocument()
  })

  it('para canchas y salas cambia el copy y usa el nombre del recurso', () => {
    // Fase 2 (2026-09-10): un recurso no tiene nombre ni apellido; el titulo
    // sale del display_name y no se habla de "profesional".
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

    renderStep()

    expect(screen.getByText('Que reservas?')).toBeInTheDocument()
    expect(screen.getByText('Cualquiera disponible')).toBeInTheDocument()
    expect(screen.getByText('Cancha 1')).toBeInTheDocument()
    expect(screen.queryByText('Cualquier profesional')).not.toBeInTheDocument()
  })
})
