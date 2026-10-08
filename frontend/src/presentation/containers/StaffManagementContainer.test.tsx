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
const mockAddMyself = jest.fn()
jest.mock('../hooks/useManagedStaff', () => ({
  useAddMyselfAsStaff: () => ({ mutateAsync: mockAddMyself }),
  useManagedStaff: () => ({
    data: [{ id: 'st-1', fullName: 'Ana Gomez', displayName: 'Ana' }],
    isLoading: false,
    error: null
  }),
  useCreateManagedStaff: () => ({ mutateAsync: jest.fn() }),
  useUpdateManagedStaff: () => ({ mutateAsync: jest.fn() }),
  useDeleteManagedStaff: () => ({ mutateAsync: mockDelete, isPending: false })
}))

let mockUser: Record<string, unknown> | null = {
  public_id: 'usr-duenio',
  role: 'store_admin',
  email: 'duenio@example.com',
  first_name: 'Enrique',
  last_name: 'Martinez'
}
jest.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockUser })
}))

let mockConfirmAnswer = true
const mockConfirm = jest.fn((_question: string) => Promise.resolve(mockConfirmAnswer))

jest.mock('../hooks/useManagedServices', () => ({
  useManagedServices: () => ({ data: [] })
}))

jest.mock('../hooks/useConfirm', () => ({
  useConfirm: () => ({ confirm: mockConfirm, confirmDialog: null })
}))

let mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
jest.mock('../hooks/useStoreWriteAccess', () => ({
  useStoreWriteAccess: () => mockWriteAccess
}))

jest.mock('../components/molecules/StaffCard', () => ({
  StaffCard: ({
    onDelete,
    readOnlyReason,
    isSelf
  }: {
    onDelete: (id: string) => void
    readOnlyReason?: string | null
    isSelf?: boolean
  }) => (
    <>
      <span data-testid="card-self">{isSelf ? 'propia' : 'ajena'}</span>
      <button type="button" onClick={() => onDelete('st-1')}>
        Borrar
      </button>
      <span data-testid="card-reason">{readOnlyReason ?? 'editable'}</span>
    </>
  )
}))

jest.mock('../components/organisms/StaffFormModal', () => ({
  StaffFormModal: ({
    readOnlyReason,
    isOpen,
    selfName,
    onSubmit
  }: {
    readOnlyReason?: string | null
    isOpen: boolean
    selfName?: string | null
    onSubmit: (data: { display_name: string; service_ids: string[] }) => Promise<void>
  }) => (
    <>
      <span data-testid="modal-reason">{readOnlyReason ?? 'editable'}</span>
      {isOpen && <span data-testid="modal-self">{selfName ?? 'no'}</span>}
      <button
        type="button"
        onClick={() => void onSubmit({ display_name: 'Enrique', service_ids: ['svc-1'] })}
      >
        Enviar modal
      </button>
    </>
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

// 2026-10-08, decision de Mateo: el dueno tambien atiende con su cuenta.
describe('StaffManagementContainer: agregarme como profesional', () => {
  afterEach(() => {
    mockUser = {
      public_id: 'usr-duenio',
      role: 'store_admin',
      email: 'duenio@example.com',
      first_name: 'Enrique',
      last_name: 'Martinez'
    }
    mockConfirmAnswer = true
    mockConfirm.mockClear()
    mockAddMyself.mockReset()
    mockDelete.mockReset()
  })

  it('el admin que no figura ve el boton y se agrega con su nombre', async () => {
    mockAddMyself.mockResolvedValue({})
    const { getByRole, getByTestId, getByText } = render(<StaffManagementContainer />)

    fireEvent.click(getByRole('button', { name: /agregarme como profesional/i }))
    expect(getByTestId('modal-self')).toHaveTextContent('Enrique Martinez')
    fireEvent.click(getByText('Enviar modal'))

    await waitFor(() =>
      expect(mockAddMyself).toHaveBeenCalledWith({ displayName: 'Enrique', serviceIds: ['svc-1'] })
    )
  })

  it('si ya figura, no hay boton y su tarjeta se marca como propia', () => {
    mockUser = { ...mockUser, public_id: 'st-1' }
    const { queryByRole, getByTestId } = render(<StaffManagementContainer />)

    expect(queryByRole('button', { name: /agregarme como profesional/i })).not.toBeInTheDocument()
    expect(getByTestId('card-self')).toHaveTextContent('propia')
  })

  it('un profesional o recepcion no ven el boton (POST /staff/me es solo para admins)', () => {
    for (const role of ['professional', 'receptionist']) {
      mockUser = { ...mockUser, role }
      const { queryByRole, unmount } = render(<StaffManagementContainer />)
      expect(queryByRole('button', { name: /agregarme como profesional/i })).not.toBeInTheDocument()
      unmount()
    }
  })

  it('quitarse de la agenda pregunta distinto: la cuenta no cambia', async () => {
    mockUser = { ...mockUser, public_id: 'st-1' }
    mockDelete.mockResolvedValue(undefined)
    const { getByText } = render(<StaffManagementContainer />)

    fireEvent.click(getByText('Borrar'))

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('st-1'))
    expect(mockConfirm).toHaveBeenCalledWith(
      '¿Quitarte de la agenda? Tu cuenta y tu acceso no cambian.'
    )
  })
})
