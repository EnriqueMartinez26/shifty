import { render, screen } from '@testing-library/react'

import CollectionsPage from './Collections'

// FF-21: la conciliacion es solo de admins; al profesional el backend le
// responde 403, asi que la pantalla no la pide ni muestra sus indicadores.
const mockUseReconciliationSummary = jest.fn((enabled?: boolean) => ({
  data: enabled ? { pending_payments: 4, total_pending_amount: '1500' } : undefined,
  error: null
}))
let mockAuthUser: { role: string; is_global_admin: boolean }
let mockAppointments: unknown[] = []
let mockFlags: { payments: boolean } | undefined = { payments: true }
let mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }

jest.mock('../hooks/useStores', () => ({
  useStoreFeatureFlags: () => ({ data: mockFlags ? { flags: mockFlags } : undefined })
}))

jest.mock('../hooks/useStoreWriteAccess', () => ({
  useStoreWriteAccess: () => mockWriteAccess
}))

jest.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockAuthUser })
}))

jest.mock('../hooks/usePayments', () => ({
  usePaymentsAppointments: () => ({ data: mockAppointments, isLoading: false, error: null }),
  useReconciliationSummary: (enabled?: boolean) => mockUseReconciliationSummary(enabled),
  useCreatePaymentPreference: () => ({ mutateAsync: jest.fn(), data: undefined }),
  useManualConfirmPayment: () => ({ mutateAsync: jest.fn() })
}))

const valorDe = (label: string) => screen.getByText(label).nextElementSibling?.textContent

describe('CollectionsPage', () => {
  beforeEach(() => {
    mockUseReconciliationSummary.mockClear()
    mockAppointments = []
    mockFlags = { payments: true }
    mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
  })

  it('al profesional no le pide la conciliacion ni le muestra pagos pendientes', () => {
    mockAuthUser = { role: 'professional', is_global_admin: false }
    render(<CollectionsPage />)

    expect(mockUseReconciliationSummary).toHaveBeenCalledWith(false)
    expect(mockUseReconciliationSummary).not.toHaveBeenCalledWith(true)
    expect(valorDe('Turnos listados')).toBe('0')
    expect(screen.queryByText('Pagos pendientes')).not.toBeInTheDocument()
    expect(screen.queryByText('Monto pendiente')).not.toBeInTheDocument()
    // Crear el link y confirmar el pago manual siguen disponibles en la pantalla.
    expect(screen.getByRole('heading', { name: 'Turnos listos para cobrar' })).toBeInTheDocument()
  })

  it.each([
    ['store_admin', false],
    ['professional', true]
  ])(
    'con el rol %s (llave global: %s) pide la conciliacion y muestra las tres tarjetas',
    (role, isGlobalAdmin) => {
      mockAuthUser = { role, is_global_admin: isGlobalAdmin }
      render(<CollectionsPage />)

      expect(mockUseReconciliationSummary).toHaveBeenCalledWith(true)
      expect(valorDe('Turnos listados')).toBe('0')
      expect(valorDe('Pagos pendientes')).toBe('4')
      expect(screen.getByText('Monto pendiente')).toBeInTheDocument()
    }
  )
})

// 2026-10-02, QA en navegador: con los cobros apagados "Crear link" y
// "Confirmar manual" estaban habilitados, fallaban con 403 y el aviso salia
// dos veces, fuera de la vista. Con la tienda suspendida tambien (402).
// 2026-10-03 (decision de Mateo): la sena por WhatsApp se confirma a mano y
// el backend ya no pide el flag de cobros para eso; solo "Crear link" (MP).
describe('CollectionsPage: cuando no se puede cobrar', () => {
  const turno = {
    public_id: 'appt-1',
    status: 'confirmed',
    client_name: 'Lucia',
    service_name: 'Corte',
    staff_name: 'Ana',
    starts_at: '2026-10-02T13:00:00Z'
  }

  beforeEach(() => {
    mockUseReconciliationSummary.mockClear()
    mockAuthUser = { role: 'store_admin', is_global_admin: false }
    mockAppointments = [turno]
    mockFlags = { payments: true }
    mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
  })

  const crearLink = () => screen.getByRole('button', { name: /Crear link/ })
  const confirmarPago = () => screen.getByRole('button', { name: /Confirmar pago/ })
  const botones = () => [crearLink(), confirmarPago()]

  it('con los cobros apagados deshabilita el link, lo dice una vez y no pide la conciliacion', () => {
    mockFlags = { payments: false }
    render(<CollectionsPage />)

    expect(crearLink()).toBeDisabled()
    expect(crearLink().getAttribute('title')).toMatch(/cobros online están apagados/)
    expect(screen.getAllByText(/cobros online están apagados/)).toHaveLength(1)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(mockUseReconciliationSummary).not.toHaveBeenCalledWith(true)
  })

  it('con los cobros apagados igual deja confirmar a mano una sena por WhatsApp', () => {
    mockFlags = { payments: false }
    mockAppointments = [{ ...turno, status: 'pending_payment' }]
    render(<CollectionsPage />)

    expect(confirmarPago()).not.toBeDisabled()
    expect(confirmarPago()).not.toHaveAttribute('title')
  })

  it('con la tienda suspendida los deshabilita con el motivo', () => {
    mockWriteAccess = { readOnly: true, reason: 'Tienda suspendida' }
    render(<CollectionsPage />)

    for (const boton of botones()) {
      expect(boton).toBeDisabled()
      expect(boton).toHaveAttribute('title', 'Tienda suspendida')
    }
  })

  it('con cobros activos y sin suspension siguen habilitados', () => {
    render(<CollectionsPage />)

    for (const boton of botones()) expect(boton).not.toBeDisabled()
  })
})
