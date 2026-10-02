import { fireEvent, render, waitFor } from '@testing-library/react'
import { toast } from 'sonner'

import { ConflictError } from '@shared/errors'

import { StaffManagementContainer } from './StaffManagementContainer'

/**
 * 2026-09-28 (FF-17). Borrar un profesional con `mutate(id)` y sin `onError`: si el
 * backend lo rechazaba, el usuario no veia nada.
 */
jest.mock('sonner', () => ({ toast: { error: jest.fn(), warning: jest.fn(), info: jest.fn() } }))

const mockDelete = jest.fn()
jest.mock('../hooks/useManagedStaff', () => ({
  useManagedStaff: () => ({
    data: [{ id: 'st-1', fullName: 'Ana Gomez', displayName: 'Ana' }],
    isLoading: false,
    error: null
  }),
  useCreateManagedStaff: () => ({ mutateAsync: jest.fn() }),
  useUpdateManagedStaff: () => ({ mutateAsync: jest.fn() }),
  useDeleteManagedStaff: () => ({ mutateAsync: mockDelete, isPending: false })
}))

jest.mock('../hooks/useConfirm', () => ({
  useConfirm: () => ({ confirm: () => Promise.resolve(true), confirmDialog: null })
}))

let mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
jest.mock('../hooks/useStoreWriteAccess', () => ({
  useStoreWriteAccess: () => mockWriteAccess
}))

jest.mock('../components/molecules/StaffCard', () => ({
  StaffCard: ({
    onDelete,
    readOnlyReason
  }: {
    onDelete: (id: string) => void
    readOnlyReason?: string | null
  }) => (
    <>
      <button type="button" onClick={() => onDelete('st-1')}>
        Borrar
      </button>
      <span data-testid="card-reason">{readOnlyReason ?? 'editable'}</span>
    </>
  )
}))

jest.mock('../components/organisms/StaffFormModal', () => ({
  StaffFormModal: ({ readOnlyReason }: { readOnlyReason?: string | null }) => (
    <span data-testid="modal-reason">{readOnlyReason ?? 'editable'}</span>
  )
}))

// 2026-10-01: con la tienda suspendida cada accion fallaba con 402 en vez de
// verse deshabilitada (FF-15). POST, PUT y DELETE /staff/... no estan en
// SUSPENSION_ALLOWED_WRITES.
describe('StaffManagementContainer: tienda suspendida', () => {
  afterEach(() => {
    mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
  })

  it('con la tienda suspendida NUEVO se deshabilita y el motivo llega a la tarjeta', () => {
    mockWriteAccess = { readOnly: true, reason: 'Tienda suspendida' }
    const { getByRole, getByTestId } = render(<StaffManagementContainer />)

    const nuevo = getByRole('button', { name: /nuevo profesional/i })
    expect(nuevo).toBeDisabled()
    expect(nuevo).toHaveAttribute('title', 'Tienda suspendida')
    expect(getByTestId('card-reason')).toHaveTextContent('Tienda suspendida')
    // 2026-10-02: el modal no recibia el motivo y su guardar fallaba con 402.
    expect(getByTestId('modal-reason')).toHaveTextContent('Tienda suspendida')
  })

  it('sin suspension NUEVO sigue habilitado y la tarjeta no recibe motivo', () => {
    const { getByRole, getByTestId } = render(<StaffManagementContainer />)

    expect(getByRole('button', { name: /nuevo profesional/i })).not.toBeDisabled()
    expect(getByTestId('card-reason')).toHaveTextContent('editable')
    expect(getByTestId('modal-reason')).toHaveTextContent('editable')
  })
})

describe('StaffManagementContainer: borrar', () => {
  it('si el backend rechaza el borrado, el usuario ve el aviso neutro', async () => {
    mockDelete.mockRejectedValue(
      new ConflictError('FK violation on appointments', {
        errorCode: 'HTTP_ERROR',
        statusCode: 500
      })
    )
    const { getByText } = render(<StaffManagementContainer />)

    fireEvent.click(getByText('Borrar'))

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith('No se pudo eliminar al profesional.')
    )
    expect(mockDelete).toHaveBeenCalledWith('st-1')
  })
})
