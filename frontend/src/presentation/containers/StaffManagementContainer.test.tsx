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

jest.mock('../components/molecules/StaffCard', () => ({
  StaffCard: ({ onDelete }: { onDelete: (id: string) => void }) => (
    <button type="button" onClick={() => onDelete('st-1')}>
      Borrar
    </button>
  )
}))

jest.mock('../components/organisms/StaffFormModal', () => ({ StaffFormModal: () => null }))

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
