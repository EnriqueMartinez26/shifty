import { render, screen } from '@testing-library/react'

import { User } from '@domain/entities/User'

import LedgerPage from './Ledger'

const cliente = (id: string, email: string, firstName: string) =>
  User.fromPrimitives({
    id,
    email,
    firstName,
    lastName: 'Gomez',
    phone: null,
    role: 'client',
    isActive: true,
    createdAt: '2026-09-01T12:00:00+00:00'
  })

const mockCustomerLedger = jest.fn()

jest.mock('../hooks/useManagedDomainUsers', () => ({
  useStoreClients: () => ({
    data: [
      cliente('cli-a', 'ana@example.com', 'Ana'),
      cliente('cli-b', 'beto@example.com', 'Beto')
    ],
    isLoading: false,
    error: null
  })
}))

jest.mock('../hooks/useLedger', () => ({
  useLedgerSummary: () => ({ data: undefined, isLoading: false, error: null }),
  useCustomerLedger: (clientId: string | null) => {
    mockCustomerLedger(clientId)
    return { data: undefined, isLoading: false, error: null }
  },
  useAddLedgerMovement: () => ({ mutateAsync: jest.fn(), isPending: false })
}))

describe('LedgerPage', () => {
  it('sin eleccion toma el primer cliente en el render y muestra su email como texto', () => {
    render(<LedgerPage />)

    expect((screen.getAllByRole('combobox')[0] as HTMLSelectElement).value).toBe('cli-a')
    expect(mockCustomerLedger).toHaveBeenCalledWith('cli-a')
    expect(mockCustomerLedger).not.toHaveBeenCalledWith(null)
    expect(screen.getByText(/ana@example\.com/)).toBeInTheDocument()
  })
})
