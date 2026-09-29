import type { ComponentProps } from 'react'

import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { ConflictError } from '@shared/errors'

import { BlocksPanel, type EditableBlock } from './BlocksPanel'

const mockUpdate = jest.fn()
const mockPreview = jest.fn()
const mockCreate = jest.fn()
const mockCreateRecurring = jest.fn()
const mockTemplatesHook = jest.fn()

jest.mock('../hooks/useAppointmentBlocks', () => ({
  useBlockTemplates: (options: { enabled: boolean }) => mockTemplatesHook(options),
  useBlockPreview: () => ({ mutateAsync: mockPreview, isPending: false }),
  useCreateAppointmentBlock: () => ({ mutateAsync: mockCreate, isPending: false }),
  useCreateRecurringAppointmentBlock: () => ({
    mutateAsync: mockCreateRecurring,
    isPending: false
  }),
  useUpdateAppointmentBlock: () => ({ mutateAsync: mockUpdate, isPending: false })
}))

const staffMembers = [
  { id: 'st-1', displayName: 'Ana Gomez' },
  { id: 'st-2', displayName: 'Beto Diaz' }
]

// 12:00 a 13:00 en Argentina del 20/09/2026.
const block: EditableBlock = {
  public_id: 'blk-1',
  staff_id: 'st-2',
  starts_at: '2026-09-20T15:00:00.000Z',
  ends_at: '2026-09-20T16:00:00.000Z',
  reason: 'Tramite'
}

const affectedPreview = {
  ranges: 1,
  affected: [
    {
      public_id: 'a1',
      client_name: 'Carla Ruiz',
      client_phone: null,
      service_name: 'Consulta',
      staff_name: 'Beto Diaz',
      starts_at: '2026-09-20T15:30:00.000Z',
      ends_at: '2026-09-20T16:00:00.000Z',
      status: 'confirmed',
      blocker: null,
      cancellable: true
    }
  ]
}

const renderPanel = (overrides: Partial<ComponentProps<typeof BlocksPanel>> = {}) => {
  const props = {
    staffMembers,
    dateStr: '2026-09-20',
    canManageBlocks: true,
    canCancelAffected: true,
    editTarget: null,
    onDoneEditing: jest.fn(),
    onMessage: jest.fn(),
    ...overrides
  }
  const view = render(<BlocksPanel {...props} />)
  return { ...view, props }
}

describe('BlocksPanel', () => {
  beforeEach(() => {
    jest.useFakeTimers({ now: new Date('2026-09-20T15:30:00.000Z') })
    ;[mockUpdate, mockPreview, mockCreate, mockCreateRecurring, mockTemplatesHook].forEach((m) =>
      m.mockReset()
    )
    mockTemplatesHook.mockReturnValue({ data: [], isLoading: false, error: null })
  })

  afterEach(() => {
    jest.useRealTimers()
  })

  // FF-11 / D-20260929-11: el PATCH no acepta staff_id; mandarlo decia
  // "actualizado" sin mover nada.
  it('editar no manda staff_id y deja el profesional fijo', async () => {
    mockUpdate.mockResolvedValue(block)
    const { props } = renderPanel({ editTarget: block })

    const staffSelect = screen.getByRole('combobox', { name: 'Profesional' })
    expect(staffSelect).toBeDisabled()
    expect((staffSelect as HTMLSelectElement).value).toBe('st-2')
    fireEvent.click(screen.getByRole('button', { name: 'Actualizar bloqueo' }))

    await waitFor(() => expect(props.onDoneEditing).toHaveBeenCalled())
    expect(mockUpdate).toHaveBeenCalledWith({
      publicId: 'blk-1',
      payload: {
        starts_at: '2026-09-20T15:00:00.000Z',
        ends_at: '2026-09-20T16:00:00.000Z',
        reason: 'Tramite'
      }
    })
    expect(props.onMessage).toHaveBeenCalledWith('Bloqueo actualizado')
  })

  // FF-11: si la edicion pasa a pisar turnos, el 409 abre la vista previa y
  // el administrador puede confirmar la cancelacion.
  it('un 409 BLOCK_HAS_APPOINTMENTS al editar abre la vista previa y confirma con cancel_affected', async () => {
    mockUpdate
      .mockRejectedValueOnce(
        new ConflictError('Hay 1 turno(s) reservado(s) dentro del bloqueo.', {
          errorCode: 'BLOCK_HAS_APPOINTMENTS',
          statusCode: 409
        })
      )
      .mockResolvedValueOnce(block)
    mockPreview.mockResolvedValue(affectedPreview)
    const { props } = renderPanel({ editTarget: block })

    fireEvent.click(screen.getByRole('button', { name: 'Actualizar bloqueo' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Cancelar 1 turno y bloquear' }))

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(2))
    expect(mockPreview).toHaveBeenCalledWith({
      staff_id: 'st-2',
      starts_at: '2026-09-20T15:00:00.000Z',
      ends_at: '2026-09-20T16:00:00.000Z',
      recurrence: 'none'
    })
    expect(mockUpdate).toHaveBeenLastCalledWith({
      publicId: 'blk-1',
      payload: {
        starts_at: '2026-09-20T15:00:00.000Z',
        ends_at: '2026-09-20T16:00:00.000Z',
        reason: 'Tramite',
        cancel_affected: true
      }
    })
    await waitFor(() => expect(props.onDoneEditing).toHaveBeenCalled())
  })

  // FF-34: el profesional no puede cancelar turnos en bloque (403).
  it('sin permiso de cancelar, el 409 muestra los turnos y pide un administrador', async () => {
    mockUpdate.mockRejectedValue(
      new ConflictError('Hay turnos', { errorCode: 'BLOCK_HAS_APPOINTMENTS', statusCode: 409 })
    )
    mockPreview.mockResolvedValue(affectedPreview)
    renderPanel({ editTarget: block, canCancelAffected: false })

    fireEvent.click(screen.getByRole('button', { name: 'Actualizar bloqueo' }))

    expect(await screen.findByText(/Pedile a un administrador que confirme/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /y bloquear/ })).not.toBeInTheDocument()
  })

  // FF-14 / D-20260929-09: recepcion ve la agenda pero no gestiona bloqueos.
  it('recepcion no ve el formulario y no pide las plantillas', () => {
    renderPanel({ canManageBlocks: false })

    expect(screen.queryByRole('button', { name: 'Guardar bloqueo' })).not.toBeInTheDocument()
    expect(mockTemplatesHook).toHaveBeenCalledWith({ enabled: false })
  })

  // FF-13 / D-20260929-10: la serie se define por fecha de fin, se muestra
  // cuantos bloqueos salen y no se guarda una que pase el tope de 120.
  it('la recurrencia por fecha de fin muestra N, frena arriba de 120 y manda N', async () => {
    mockPreview.mockResolvedValue({ ranges: 8, affected: [] })
    mockCreateRecurring.mockResolvedValue({ created: 8, blocks: [] })
    const { props } = renderPanel()

    fireEvent.change(screen.getByLabelText('Recurrencia'), { target: { value: 'daily' } })
    const until = screen.getByLabelText('Repetir hasta')
    fireEvent.change(until, { target: { value: '2027-01-31' } })
    expect(screen.getByText(/Se crearían 134 bloqueos/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Guardar bloqueo' })).toBeDisabled()

    fireEvent.change(until, { target: { value: '2026-09-27' } })
    expect(screen.getByText('Se crearán 8 bloqueos')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Guardar bloqueo' }))

    await waitFor(() => expect(mockCreateRecurring).toHaveBeenCalled())
    expect(mockPreview).toHaveBeenCalledWith(expect.objectContaining({ max_occurrences: 8 }))
    expect(mockCreateRecurring).toHaveBeenCalledWith(
      expect.objectContaining({ staff_id: 'st-1', recurrence: 'daily', max_occurrences: 8 })
    )
    expect(props.onMessage).toHaveBeenCalledWith('Serie de bloqueos creada')
  })
})
