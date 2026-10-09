import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { CalendarContainer } from './CalendarContainer'

const mockUpdateBlock = jest.fn()
const idleMutation = { mutateAsync: jest.fn(), isPending: false }

// 12:00 a 13:00 en Argentina del 20/09/2026.
const mockBlock = {
  public_id: 'blk-1',
  staff_id: 'st-1',
  starts_at: '2026-09-20T15:00:00.000Z',
  ends_at: '2026-09-20T16:00:00.000Z',
  reason: 'Tramite',
  is_active: true
}

// FF-12: el servidor ya filtra los inactivos, pero la agenda tampoco los
// muestra si llegan (otra version del backend, cache vieja).
const mockInactiveBlock = {
  ...mockBlock,
  public_id: 'blk-2',
  reason: 'Desactivado',
  is_active: false
}

const mockBlocksHook = jest.fn()
jest.mock('../hooks/useAppointmentBlocks', () => ({
  useAppointmentBlocks: (...args: unknown[]) => mockBlocksHook(...args),
  useBlockTemplates: () => ({ data: [], isLoading: false, error: null }),
  useBlockPreview: () => idleMutation,
  useCreateAppointmentBlock: () => idleMutation,
  useCreateRecurringAppointmentBlock: () => idleMutation,
  useDeleteAppointmentBlock: () => idleMutation,
  useUpdateAppointmentBlock: () => ({ mutateAsync: mockUpdateBlock, isPending: false })
}))

jest.mock('../hooks/useCalendarAgenda', () => ({
  useCalendarAgenda: () => ({
    data: { appointments: [], total: 0 },
    isLoading: false,
    error: null
  }),
  useCancelAppointment: () => idleMutation,
  useCompleteAppointment: () => idleMutation,
  useConfirmAppointment: () => idleMutation,
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

jest.mock('../hooks/useStoreWriteAccess', () => ({
  useStoreWriteAccess: () => ({ readOnly: false, reason: '' })
}))

describe('CalendarContainer - formulario de bloqueo (F11c-05)', () => {
  beforeEach(() => {
    jest.useFakeTimers({ now: new Date('2026-09-20T15:30:00.000Z') })
    mockUpdateBlock.mockReset()
    mockUpdateBlock.mockResolvedValue(mockBlock)
    mockBlocksHook.mockReset()
    mockBlocksHook.mockReturnValue({
      data: [mockBlock, mockInactiveBlock],
      isLoading: false,
      error: null
    })
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  // Sintoma: "Editar" el bloqueo del 20, flecha al dia siguiente y
  // "Actualizar bloqueo" lo movia al 21 sin que nadie tocara la fecha.
  it('navegar el calendario mientras se edita no mueve el bloqueo de dia', async () => {
    const { container } = render(<CalendarContainer />)

    fireEvent.click(screen.getByRole('button', { name: 'Editar' }))
    const next = container.querySelector('.lucide-chevron-right')?.closest('button')
    if (!next) throw new Error('No encontre la flecha para avanzar el dia')
    fireEvent.click(next)
    fireEvent.click(screen.getByRole('button', { name: 'Actualizar bloqueo' }))

    await waitFor(() => expect(mockUpdateBlock).toHaveBeenCalled())
    expect(mockUpdateBlock).toHaveBeenCalledWith({
      publicId: 'blk-1',
      // Sin staff_id: el PATCH no lo acepta (FF-11, D-20260929-11).
      payload: {
        starts_at: '2026-09-20T15:00:00.000Z',
        ends_at: '2026-09-20T16:00:00.000Z',
        reason: 'Tramite'
      }
    })
  })

  it('un bloqueo nuevo sigue al dia que muestra el calendario', () => {
    const { container } = render(<CalendarContainer />)

    const dateInput = container.querySelector('input[type="date"]') as HTMLInputElement
    expect(dateInput.value).toBe('2026-09-20')
    const next = container.querySelector('.lucide-chevron-right')?.closest('button')
    if (!next) throw new Error('No encontre la flecha para avanzar el dia')
    fireEvent.click(next)
    expect(dateInput.value).toBe('2026-09-21')
  })

  it('pide los bloqueos del rango visible y no lista los desactivados (FF-12)', () => {
    render(<CalendarContainer />)

    expect(mockBlocksHook).toHaveBeenCalledWith('2026-09-20', '2026-09-20')
    expect(screen.getAllByText('Tramite').length).toBeGreaterThan(0)
    expect(screen.queryByText('Desactivado')).not.toBeInTheDocument()
  })

  // FF-14 / D-20260929-09: recepcion ve los bloqueos, pero no los gestiona.
  it('recepcion ve el bloqueo sin formulario ni acciones', () => {
    mockUser.role = 'receptionist'
    try {
      render(<CalendarContainer />)

      expect(screen.getAllByText('Tramite').length).toBeGreaterThan(0)
      expect(screen.queryByRole('button', { name: 'Editar' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Desactivar' })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Guardar bloqueo' })).not.toBeInTheDocument()
    } finally {
      mockUser.role = 'store_admin'
    }
  })
})
