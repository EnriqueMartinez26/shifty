import { fireEvent, render, waitFor } from '@testing-library/react'
import { toast } from 'sonner'

import { ConflictError } from '@shared/errors'

import { ServiceManagementContainer } from './ServiceManagementContainer'
import { notifyError } from '../lib/notify'
import type * as NotifyModule from '../lib/notify'

/**
 * 2026-09-28 (FF-17). Borrar un servicio con `mutate(id)` y sin `onError`: si el
 * backend lo rechazaba, el usuario no veia nada.
 */
jest.mock('sonner', () => ({ toast: { error: jest.fn(), warning: jest.fn(), info: jest.fn() } }))

// Espia sobre el real: el caso de borrado sigue verificando el toast.
jest.mock('../lib/notify', () => {
  const actual = jest.requireActual<typeof NotifyModule>('../lib/notify')
  return { ...actual, notifyError: jest.fn(actual.notifyError) }
})

const mockDelete = jest.fn()
const mockUpdate = jest.fn()
const mockListShared = jest.fn()
const mockListCatalog = jest.fn(() => ({
  data: [{ id: 'svc-1', name: 'Corte' }],
  isLoading: false,
  error: null
}))
jest.mock('../hooks/useManagedServices', () => ({
  useManagedServices: () => mockListShared(),
  useManagedServiceCatalog: () => mockListCatalog(),
  useCreateManagedService: () => ({ mutateAsync: jest.fn() }),
  useUpdateManagedService: () => ({ mutateAsync: mockUpdate }),
  useDeleteManagedService: () => ({ mutateAsync: mockDelete, isPending: false }),
  useUploadServiceImage: () => ({ mutateAsync: jest.fn() }),
  useRemoveServiceImage: () => ({ mutateAsync: jest.fn() })
}))

jest.mock('../hooks/useConfirm', () => ({
  useConfirm: () => ({ confirm: () => Promise.resolve(true), confirmDialog: null })
}))

let mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
jest.mock('../hooks/useStoreWriteAccess', () => ({
  useStoreWriteAccess: () => mockWriteAccess
}))

jest.mock('../components/molecules/ServiceCard', () => ({
  ServiceCard: ({
    onDelete,
    onReactivate,
    readOnlyReason
  }: {
    onDelete: (id: string) => void
    onReactivate: (id: string) => void
    readOnlyReason?: string | null
  }) => (
    <>
      <button type="button" onClick={() => onDelete('svc-1')}>
        Borrar
      </button>
      <button type="button" onClick={() => onReactivate('svc-1')}>
        Reactivar
      </button>
      <span data-testid="card-reason">{readOnlyReason ?? 'editable'}</span>
    </>
  )
}))

const mockFormModal = jest.fn((_props: { readOnlyReason?: string | null }) => null)
jest.mock('../components/organisms/ServiceFormModal', () => ({
  ServiceFormModal: (props: { readOnlyReason?: string | null }) => mockFormModal(props)
}))

// 2026-10-01: con la tienda suspendida cada accion fallaba con 402 en vez de
// verse deshabilitada (FF-15). POST, PATCH y DELETE /services/... (imagen
// incluida) no estan en SUSPENSION_ALLOWED_WRITES.
describe('ServiceManagementContainer: tienda suspendida', () => {
  afterEach(() => {
    mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
  })

  it('con la tienda suspendida NUEVO se deshabilita y el motivo llega a la tarjeta y al modal', () => {
    mockWriteAccess = { readOnly: true, reason: 'Tienda suspendida' }
    const { getByRole, getByTestId } = render(<ServiceManagementContainer />)

    const nuevo = getByRole('button', { name: /nuevo servicio/i })
    expect(nuevo).toBeDisabled()
    expect(nuevo).toHaveAttribute('title', 'Tienda suspendida')
    expect(getByTestId('card-reason')).toHaveTextContent('Tienda suspendida')
    expect(mockFormModal).toHaveBeenLastCalledWith(
      expect.objectContaining({ readOnlyReason: 'Tienda suspendida' })
    )
  })

  it('sin suspension NUEVO sigue habilitado y la tarjeta no recibe motivo', () => {
    const { getByRole, getByTestId } = render(<ServiceManagementContainer />)

    expect(getByRole('button', { name: /nuevo servicio/i })).not.toBeDisabled()
    expect(getByTestId('card-reason')).toHaveTextContent('editable')
  })
})

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

/**
 * 2026-09-30 (FF-22): un servicio eliminado o desactivado desaparecia del panel
 * y no se podia reactivar.
 */
describe('ServiceManagementContainer: catalogo y reactivar', () => {
  beforeEach(() => {
    mockUpdate.mockReset()
    jest.mocked(notifyError).mockClear()
  })

  it('lista el catalogo con inactivos, no la lista compartida de activos', () => {
    render(<ServiceManagementContainer />)

    expect(mockListCatalog).toHaveBeenCalled()
    expect(mockListShared).not.toHaveBeenCalled()
  })

  it('reactivar manda `isActive: true` por la edicion', async () => {
    mockUpdate.mockResolvedValue({ id: 'svc-1' })
    const { getByText } = render(<ServiceManagementContainer />)

    fireEvent.click(getByText('Reactivar'))

    await waitFor(() =>
      expect(mockUpdate).toHaveBeenCalledWith({ id: 'svc-1', data: { isActive: true } })
    )
    expect(notifyError).not.toHaveBeenCalled()
  })

  it('si la reactivacion falla, avisa con notifyError y su mensaje', async () => {
    const rechazo = new ConflictError('choque', { errorCode: 'HTTP_ERROR', statusCode: 500 })
    mockUpdate.mockRejectedValue(rechazo)
    const { getByText } = render(<ServiceManagementContainer />)

    fireEvent.click(getByText('Reactivar'))

    await waitFor(() =>
      expect(notifyError).toHaveBeenCalledWith(rechazo, 'No se pudo reactivar el servicio.')
    )
  })
})
