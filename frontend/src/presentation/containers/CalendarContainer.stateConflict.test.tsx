import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { ValidationError } from '@shared/errors'

import { CalendarContainer } from './CalendarContainer'

const mockConfirm = jest.fn()
const mockRefetch = jest.fn()
const idleMutation = { mutateAsync: jest.fn(), isPending: false }

// 14:00 a 15:00 en Argentina del 20/09/2026, todavia no empezo.
const mockAppointment = {
  id: 'appt-1',
  status: 'pending',
  staffId: 'st-1',
  staffName: 'Ana Gomez',
  clientName: 'Luis Perez',
  serviceName: 'Corte',
  clientPhone: null,
  serviceId: 'svc-1',
  timeSpan: {
    getStartsAt: () => new Date('2026-09-20T17:00:00.000Z'),
    getEndsAt: () => new Date('2026-09-20T18:00:00.000Z')
  }
}

jest.mock('../hooks/useAppointmentBlocks', () => ({
  useAppointmentBlocks: () => ({ data: [], isLoading: false, error: null }),
  useBlockTemplates: () => ({ data: [], isLoading: false, error: null }),
  useBlockPreview: () => idleMutation,
  useCreateAppointmentBlock: () => idleMutation,
  useCreateRecurringAppointmentBlock: () => idleMutation,
  useDeleteAppointmentBlock: () => idleMutation,
  useUpdateAppointmentBlock: () => idleMutation
}))

jest.mock('../hooks/useCalendarAgenda', () => ({
  useCalendarAgenda: () => ({
    data: { appointments: [mockAppointment], total: 1 },
    isLoading: false,
    error: null,
    refetch: mockRefetch
  }),
  useCancelAppointment: () => idleMutation,
  useCompleteAppointment: () => idleMutation,
  useConfirmAppointment: () => ({ mutateAsync: mockConfirm, isPending: false }),
  useMarkAbsentAppointment: () => idleMutation,
  useReleaseAppointment: () => idleMutation,
  useRescheduleAppointment: () => idleMutation
}))

jest.mock('../hooks/useManagedStaff', () => ({
  useManagedStaff: () => ({
    data: [{ id: 'st-1', displayName: 'Ana Gomez', isActive: true, schedules: [] }],
    isLoading: false,
    error: null
  })
}))

jest.mock('../hooks/useStores', () => ({
  useStoreSettings: () => ({ data: { name: 'Peluqueria Sol', slug: 'sol' } })
}))

const mockUser = { role: 'store_admin', is_global_admin: false }
jest.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockUser })
}))

jest.mock('../components/organisms/NewAppointmentModal', () => ({
  NewAppointmentModal: () => null
}))

describe('CalendarContainer - desfasaje de estado (FF-02)', () => {
  beforeEach(() => {
    jest.useFakeTimers({ now: new Date('2026-09-20T15:30:00.000Z') })
    mockConfirm.mockReset()
    mockRefetch.mockReset()
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  // Sintoma: isStateConflictError leia `response.data.error_code`, que el
  // cliente HTTP ya no deja; el turno que otro ya habia cambiado mostraba el
  // texto crudo del servidor y la agenda quedaba vieja.
  it('un INVALID_STATUS_TRANSITION explica el problema y recarga la agenda', async () => {
    mockConfirm.mockRejectedValue(
      new ValidationError("No se puede pasar de 'cancelled' a 'confirmed'.", {
        errorCode: 'INVALID_STATUS_TRANSITION',
        statusCode: 422
      })
    )
    render(<CalendarContainer />)

    const [confirmTurno] = screen.getAllByRole('button', { name: 'Confirmar turno' })
    if (!confirmTurno) throw new Error('No encontre la accion de confirmar el turno')
    fireEvent.click(confirmTurno)
    fireEvent.click(await screen.findByRole('button', { name: 'Confirmar' }))

    await waitFor(() => expect(mockRefetch).toHaveBeenCalledTimes(1))
    expect(
      screen.getByText(
        'El turno ya cambió de estado. Actualizá la agenda para ver cómo está ahora.'
      )
    ).toBeInTheDocument()
  })
})
