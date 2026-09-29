import { fireEvent, render, waitFor } from '@testing-library/react'
import { toast } from 'sonner'

import { ConflictError } from '@shared/errors'

import { ServiceManagementContainer } from './ServiceManagementContainer'

/**
 * 2026-09-28 (FF-17). Borrar un servicio con `mutate(id)` y sin `onError`: si el
 * backend lo rechazaba, el usuario no veia nada.
 */
jest.mock('sonner', () => ({ toast: { error: jest.fn(), warning: jest.fn(), info: jest.fn() } }))

const mockDelete = jest.fn()
jest.mock('../hooks/useManagedServices', () => ({
  useManagedServices: () => ({
    data: [{ id: 'svc-1', name: 'Corte' }],
    isLoading: false,
    error: null
  }),
  useCreateManagedService: () => ({ mutateAsync: jest.fn() }),
  useUpdateManagedService: () => ({ mutateAsync: jest.fn() }),
  useDeleteManagedService: () => ({ mutateAsync: mockDelete, isPending: false })
}))

jest.mock('../hooks/useConfirm', () => ({
  useConfirm: () => ({ confirm: () => Promise.resolve(true), confirmDialog: null })
}))

jest.mock('../components/molecules/ServiceCard', () => ({
  ServiceCard: ({ onDelete }: { onDelete: (id: string) => void }) => (
    <button type="button" onClick={() => onDelete('svc-1')}>
      Borrar
    </button>
  )
}))

jest.mock('../components/organisms/ServiceFormModal', () => ({ ServiceFormModal: () => null }))

describe('ServiceManagementContainer: borrar', () => {
  it('si el backend rechaza el borrado, el usuario ve el aviso neutro', async () => {
    mockDelete.mockRejectedValue(
      new ConflictError('FK violation on appointments', {
        errorCode: 'HTTP_ERROR',
        statusCode: 500
      })
    )
    const { getByText } = render(<ServiceManagementContainer />)

    fireEvent.click(getByText('Borrar'))

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith('No se pudo eliminar el servicio.')
    )
    expect(mockDelete).toHaveBeenCalledWith('svc-1')
  })
})
