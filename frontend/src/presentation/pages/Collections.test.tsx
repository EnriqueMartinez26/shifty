import { act, fireEvent, render, screen, within } from '@testing-library/react'

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
const mockManualConfirm = jest.fn()
const mockCreatePreference = jest.fn()
const mockRecordRemaining = jest.fn()
const mockRevertRemaining = jest.fn()

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
  useCreatePaymentPreference: () => ({ mutateAsync: mockCreatePreference, data: undefined }),
  useManualConfirmPayment: () => ({ mutateAsync: mockManualConfirm, isPending: false }),
  useRecordRemainingPayment: () => ({ mutateAsync: mockRecordRemaining, isPending: false }),
  useRevertRemainingPayment: () => ({ mutateAsync: mockRevertRemaining, isPending: false })
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

// 2026-10-08, QA en el celular (decision de Mateo):
// - un turno "Completado" desaparecia de Cobros, y el flujo natural es atender,
//   completar y DESPUES cobrar (el backend lo cobra, regla 3);
// - "Confirmar pago" registraba al instante, sin confirmar ni pedir importe;
// - despues de pagar la tarjeta seguia igual (CONFIRMADO y el mismo boton);
// - el aviso de exito mostraba un id crudo (ULID), y la regla 20 dice que
//   los ids no salen a la persona.
describe('CollectionsPage: confirmar un pago', () => {
  const turno = {
    public_id: '01JA8ZK3Q4R5S6T7V8W9X0Y1Z2',
    status: 'confirmed',
    client_name: 'Lucia',
    service_name: 'Corte',
    staff_name: 'Ana',
    starts_at: '2026-10-08T13:00:00Z',
    price_amount: '3200.00',
    payment_status: null,
    payment_amount: null
  }
  const PAYMENT_ID = '01JA8ZPAGO000000000000000'

  beforeEach(() => {
    mockAuthUser = { role: 'store_admin', is_global_admin: false }
    mockFlags = { payments: true }
    mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
    mockAppointments = [turno]
    mockManualConfirm.mockReset()
    mockManualConfirm.mockResolvedValue({
      public_id: PAYMENT_ID,
      appointment_id: turno.public_id,
      amount: '3200.00',
      currency: 'ARS',
      status: 'manual_confirmed'
    })
    mockCreatePreference.mockReset()
  })

  const confirmarPago = () => screen.getByRole('button', { name: /Confirmar pago/ })
  const registrar = () => screen.getByRole('button', { name: /Registrar pago/ })

  it.each(['completed', 'absent'])('un turno %s sigue en Cobros y se puede cobrar', (status) => {
    mockAppointments = [{ ...turno, status }]
    render(<CollectionsPage />)

    expect(screen.getByText('Lucia')).toBeInTheDocument()
    expect(confirmarPago()).not.toBeDisabled()
  })

  it.each(['cancelled', 'expired'])('un turno %s (soltado) no aparece', (status) => {
    mockAppointments = [{ ...turno, status }]
    render(<CollectionsPage />)

    expect(screen.queryByText('Lucia')).not.toBeInTheDocument()
  })

  it('pide confirmacion con el importe antes de registrar', async () => {
    render(<CollectionsPage />)

    fireEvent.click(confirmarPago())
    expect(screen.getByRole('dialog', { name: /Confirmar pago/ })).toBeInTheDocument()
    expect(mockManualConfirm).not.toHaveBeenCalled()
    expect((screen.getByLabelText(/Importe/) as HTMLInputElement).value).toBe('3.200')

    await act(async () => {
      fireEvent.click(registrar())
    })

    // Sin cobro vivo el importe que se mostro viaja siempre: el backend no
    // tiene un cobro cuyo importe conservar (revision de la PR #131, C1).
    expect(mockManualConfirm).toHaveBeenCalledWith({
      appointmentId: turno.public_id,
      amount: 3200
    })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  // Revision de la PR #131 (C1, 2026-10-08): el importe del dialogo no
  // siempre era el registrado. Sin `amount` el backend registra el importe
  // del cobro VIVO; en cualquier otro caso el front manda el que mostro.
  it.each(['pending', 'rejected'])(
    'con un cobro vivo (%s) sin tocar el importe no lo manda: se registra el del cobro',
    async (paymentStatus) => {
      mockAppointments = [{ ...turno, payment_status: paymentStatus, payment_amount: '960.00' }]
      render(<CollectionsPage />)

      fireEvent.click(confirmarPago())
      expect((screen.getByLabelText(/Importe/) as HTMLInputElement).value).toBe('960')
      await act(async () => {
        fireEvent.click(registrar())
      })

      expect(mockManualConfirm).toHaveBeenCalledWith({
        appointmentId: turno.public_id,
        amount: undefined
      })
    }
  )

  it('con el cobro vencido manda explicito el importe que mostro', async () => {
    mockAppointments = [{ ...turno, payment_status: 'expired', payment_amount: '960.00' }]
    render(<CollectionsPage />)

    fireEvent.click(confirmarPago())
    expect((screen.getByLabelText(/Importe/) as HTMLInputElement).value).toBe('3.200')
    await act(async () => {
      fireEvent.click(registrar())
    })

    expect(mockManualConfirm).toHaveBeenCalledWith({
      appointmentId: turno.public_id,
      amount: 3200
    })
  })

  it('con un cobro vivo y el importe cambiado manda el nuevo', async () => {
    mockAppointments = [{ ...turno, payment_status: 'pending', payment_amount: '960.00' }]
    render(<CollectionsPage />)

    fireEvent.click(confirmarPago())
    fireEvent.change(screen.getByLabelText(/Importe/), { target: { value: '3.200' } })
    await act(async () => {
      fireEvent.click(registrar())
    })

    expect(mockManualConfirm).toHaveBeenCalledWith({
      appointmentId: turno.public_id,
      amount: 3200
    })
  })

  // Revision de la PR #131 (S1): el link del panel por el precio completo no
  // es una sena.
  it('un cobro vivo por el precio completo dice "Pago pendiente", no "Seña"', () => {
    mockAppointments = [{ ...turno, payment_status: 'pending', payment_amount: '3200.00' }]
    render(<CollectionsPage />)

    expect(screen.getByText(/Pago pendiente/)).toHaveTextContent('3.200')
    expect(screen.queryByText(/Seña pendiente/)).not.toBeInTheDocument()
  })

  it('un importe cambiado viaja tal cual', async () => {
    render(<CollectionsPage />)

    fireEvent.click(confirmarPago())
    fireEvent.change(screen.getByLabelText(/Importe/), { target: { value: '2500' } })
    await act(async () => {
      fireEvent.click(registrar())
    })

    expect(mockManualConfirm).toHaveBeenCalledWith({
      appointmentId: turno.public_id,
      amount: 2500
    })
  })

  it('con una sena pendiente precarga la sena', () => {
    mockAppointments = [{ ...turno, payment_status: 'pending', payment_amount: '960.00' }]
    render(<CollectionsPage />)

    expect(screen.getByText(/Seña pendiente/)).toHaveTextContent('960')
    fireEvent.click(confirmarPago())
    expect((screen.getByLabelText(/Importe/) as HTMLInputElement).value).toBe('960')
  })

  it('el aviso de exito no muestra ids crudos', async () => {
    render(<CollectionsPage />)

    fireEvent.click(confirmarPago())
    await act(async () => {
      fireEvent.click(registrar())
    })

    expect(screen.getByText(/Pago registrado/)).toHaveTextContent('Lucia')
    expect(document.body.textContent).not.toContain(PAYMENT_ID)
    expect(document.body.textContent).not.toContain(turno.public_id)
  })

  it('si falla, el error se ve en el dialogo y no se cierra', async () => {
    mockManualConfirm.mockRejectedValue(new Error('boom'))
    render(<CollectionsPage />)

    fireEvent.click(confirmarPago())
    await act(async () => {
      fireEvent.click(registrar())
    })

    expect(screen.getByRole('dialog')).toHaveTextContent('No se pudo registrar el pago')
  })

  it('el aviso del link creado no muestra ids crudos', async () => {
    mockCreatePreference.mockResolvedValue({
      payment_public_id: PAYMENT_ID,
      appointment_id: turno.public_id,
      amount: 3200,
      currency: 'ARS',
      status: 'pending'
    })
    render(<CollectionsPage />)

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Crear link/ }))
    })

    expect(screen.getByText(/Link de cobro creado/)).toHaveTextContent('Lucia')
    expect(document.body.textContent).not.toContain(PAYMENT_ID)
  })

  it('un turno pagado muestra lo pagado y lo que resta, sin volver a ofrecer cobrar', () => {
    mockAppointments = [{ ...turno, payment_status: 'approved', payment_amount: '960.00' }]
    render(<CollectionsPage />)

    expect(screen.getByText(/Pagado/)).toHaveTextContent('960')
    expect(screen.getByText(/Resta/)).toHaveTextContent('2.240')
    expect(screen.queryByRole('button', { name: /Confirmar pago/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Crear link/ })).not.toBeInTheDocument()
  })
})

// Saldo restante por turno (D-20261008-01): una sena de $960 acreditada sobre
// un turno de $3.200 deja $2.240 que el cliente paga en el local. Cobros
// ofrece registrar ese resto, con el importe precargado y el medio de pago.
describe('CollectionsPage: registrar el resto', () => {
  const turno = {
    public_id: '01JA8ZK3Q4R5S6T7V8W9X0Y1Z2',
    status: 'completed',
    client_name: 'Lucia',
    service_name: 'Corte',
    staff_name: 'Ana',
    starts_at: '2026-10-08T13:00:00Z',
    price_amount: '3200.00',
    payment_status: 'approved',
    payment_amount: '960.00',
    remaining_amount: '2240.00',
    remainder_payment: null
  }
  const saldado = {
    ...turno,
    remaining_amount: '0.00',
    remainder_payment: {
      amount: '2240.00',
      method: 'efectivo',
      created_at: '2026-10-08T15:00:00Z'
    }
  }

  beforeEach(() => {
    mockAuthUser = { role: 'store_admin', is_global_admin: false }
    mockFlags = { payments: true }
    mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
    mockAppointments = [turno]
    mockRecordRemaining.mockReset()
    mockRecordRemaining.mockResolvedValue({
      public_id: '01JA8ZREST000000000000000',
      appointment_id: turno.public_id,
      amount: '2240.00',
      method: 'efectivo',
      created_at: '2026-10-08T15:00:00Z',
      reverted_at: null,
      remaining_amount: '0.00'
    })
    mockRevertRemaining.mockReset()
    mockRevertRemaining.mockResolvedValue({ public_id: '01JA8ZREST000000000000000' })
  })

  const registrarResto = () => screen.getByRole('button', { name: /Registrar resto/ })

  it('pide el resto precargado y lo registra con el medio de pago y una clave', async () => {
    render(<CollectionsPage />)

    expect(screen.getByText(/Resta/)).toHaveTextContent('2.240')
    fireEvent.click(registrarResto())
    const dialogo = screen.getByRole('dialog', { name: /Registrar resto/ })
    expect((screen.getByLabelText(/Importe/) as HTMLInputElement).value).toBe('2.240')
    fireEvent.change(screen.getByLabelText(/Medio de pago/), { target: { value: 'efectivo' } })
    await act(async () => {
      fireEvent.click(within(dialogo).getByRole('button', { name: /Registrar resto/ }))
    })

    expect(mockRecordRemaining).toHaveBeenCalledWith({
      appointmentId: turno.public_id,
      amount: 2240,
      method: 'efectivo',
      idempotencyKey: expect.any(String)
    })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(screen.getByText(/Resto registrado/)).toHaveTextContent('Lucia')
    expect(document.body.textContent).not.toContain('01JA8ZREST')
  })

  it('un reintento desde el mismo dialogo reusa la clave', async () => {
    mockRecordRemaining.mockRejectedValueOnce(new Error('red'))
    render(<CollectionsPage />)

    fireEvent.click(registrarResto())
    const dialogo = screen.getByRole('dialog', { name: /Registrar resto/ })
    const enviar = () => within(dialogo).getByRole('button', { name: /Registrar resto/ })
    await act(async () => {
      fireEvent.click(enviar())
    })
    expect(dialogo).toHaveTextContent('No se pudo registrar el resto')
    await act(async () => {
      fireEvent.click(enviar())
    })

    const [primera, segunda] = mockRecordRemaining.mock.calls.map(
      ([vars]) => (vars as { idempotencyKey: string }).idempotencyKey
    )
    expect(primera).toBe(segunda)
  })

  it('con el resto registrado muestra el total y no lo vuelve a ofrecer', () => {
    mockAppointments = [saldado]
    render(<CollectionsPage />)

    expect(screen.getByText(/Pagado/)).toHaveTextContent('3.200')
    expect(screen.queryByRole('button', { name: /Registrar resto/ })).not.toBeInTheDocument()
  })

  it('con la tienda suspendida lo deshabilita con el motivo', () => {
    mockWriteAccess = { readOnly: true, reason: 'Tienda suspendida' }
    render(<CollectionsPage />)

    expect(registrarResto()).toBeDisabled()
    expect(registrarResto()).toHaveAttribute('title', 'Tienda suspendida')
  })

  it('el admin revierte el resto despues de confirmar', async () => {
    mockAppointments = [saldado]
    render(<CollectionsPage />)

    fireEvent.click(screen.getByRole('button', { name: /Revertir resto/ }))
    expect(mockRevertRemaining).not.toHaveBeenCalled()
    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: /Sí, revertir/ }))
    })

    expect(mockRevertRemaining).toHaveBeenCalledWith(turno.public_id)
    expect(screen.getByText(/Resto revertido/)).toHaveTextContent('Lucia')
  })

  it('el profesional no ve revertir (solo admin)', () => {
    mockAuthUser = { role: 'professional', is_global_admin: false }
    mockAppointments = [saldado]
    render(<CollectionsPage />)

    expect(screen.queryByRole('button', { name: /Revertir resto/ })).not.toBeInTheDocument()
  })
})
