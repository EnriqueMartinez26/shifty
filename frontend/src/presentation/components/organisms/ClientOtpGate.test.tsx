import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { isOtpStillValid, rememberOtpVerification } from '@shared/utils/otpSession'

import { ClientOtpGate } from './ClientOtpGate'

const mockRequestOtp = jest.fn()
const mockVerifyOtp = jest.fn()

jest.mock('../../hooks/usePublic', () => ({
  useRequestPublicOtp: () => ({ mutateAsync: mockRequestOtp, isPending: false }),
  useVerifyPublicOtp: () => ({ mutateAsync: mockVerifyOtp, isPending: false })
}))

describe('ClientOtpGate', () => {
  const onVerified = jest.fn()

  beforeEach(() => {
    onVerified.mockReset()
    mockRequestOtp.mockReset().mockResolvedValue({ expires_at: '', debug_code: '' })
    mockVerifyOtp.mockReset()
    try {
      window.sessionStorage.clear()
    } catch {
      // sin storage: la puerta igual funciona
    }
  })

  it('initialPhone precarga el telefono', () => {
    render(
      <ClientOtpGate
        storePublicId="store-1"
        storeSlug="sol"
        onVerified={onVerified}
        initialPhone="1155550101"
      />
    )

    expect((screen.getByLabelText('Teléfono') as HTMLInputElement).value).toBe('1155550101')
  })

  it('con skipRemembered olvida la verificacion recordada y pide un codigo nuevo', async () => {
    // FF-05 (2026-09-30): el backend rechazo con 403 OTP_VERIFICATION_REQUIRED
    // una verificacion que el dispositivo daba por vigente; entrar por el
    // atajo repetia el 403 sin mandar ningun codigo.
    rememberOtpVerification('sol', '1155550101', new Date().toISOString())

    render(
      <ClientOtpGate
        storePublicId="store-1"
        storeSlug="sol"
        onVerified={onVerified}
        initialPhone="1155550101"
        skipRemembered
      />
    )
    fireEvent.change(screen.getByLabelText('Tu email'), { target: { value: 'yo@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enviarme el código' }))

    expect(await screen.findByLabelText('Código')).toBeInTheDocument()
    expect(mockRequestOtp).toHaveBeenCalledWith({
      store_public_id: 'store-1',
      phone: '1155550101',
      channel: 'email',
      email: 'yo@example.com'
    })
    expect(isOtpStillValid('sol', '1155550101')).toBe(false)
    expect(onVerified).not.toHaveBeenCalled()
  })

  it('sin skipRemembered y con la verificacion vigente entra directo', async () => {
    rememberOtpVerification('sol', '1155550101', new Date().toISOString())

    render(<ClientOtpGate storePublicId="store-1" storeSlug="sol" onVerified={onVerified} />)
    fireEvent.change(screen.getByLabelText('Teléfono'), { target: { value: '1155550101' } })
    fireEvent.click(screen.getByRole('button', { name: 'Enviarme el código' }))

    await waitFor(() => expect(onVerified).toHaveBeenCalledWith('1155550101'))
    expect(mockRequestOtp).not.toHaveBeenCalled()
    expect(isOtpStillValid('sol', '1155550101')).toBe(true)
  })
})

const PEDIR = 'Enviarme el código'

const renderGate = () => {
  const onVerified = jest.fn()
  render(<ClientOtpGate storePublicId="store-1" storeSlug="sol" onVerified={onVerified} />)
  return onVerified
}

const pedirCodigo = async (phone = '1155550101') => {
  fireEvent.change(screen.getByLabelText('Teléfono'), { target: { value: phone } })
  fireEvent.change(screen.getByLabelText('Tu email'), { target: { value: 'yo@example.com' } })
  await act(async () => {
    fireEvent.click(screen.getByRole('button', { name: PEDIR }))
  })
}

describe('ClientOtpGate en el celular (F4-11, J7)', () => {
  // 2026-09-30, F4-11: sin espera para reenviar, volver y tocar "Enviarme el
  // código" mientras el mail tardaba gastaba uno de los 5 pedidos por hora
  // (OTP_MAX_REQUESTS_PER_HOUR) y el cliente quedaba bloqueado una hora.
  beforeEach(() => {
    jest.useFakeTimers()
    mockRequestOtp.mockReset().mockResolvedValue({ ok: true, expires_at: '' })
    mockVerifyOtp.mockReset()
    window.sessionStorage.clear()
  })
  afterEach(() => jest.useRealTimers())

  it('despues de un pedido exitoso espera 60 s para reenviar y muestra los segundos', async () => {
    renderGate()
    await pedirCodigo()
    fireEvent.click(screen.getByRole('button', { name: 'Cambiar teléfono o email' }))

    expect(screen.getByRole('button', { name: 'Reenviar en 60 s' })).toBeDisabled()
    act(() => {
      jest.advanceTimersByTime(45_000)
    })
    expect(screen.getByRole('button', { name: 'Reenviar en 15 s' })).toBeDisabled()
    act(() => {
      jest.advanceTimersByTime(15_000)
    })
    expect(screen.getByRole('button', { name: PEDIR })).not.toBeDisabled()
    expect(mockRequestOtp).toHaveBeenCalledTimes(1)
  })

  it('un pedido fallido no arranca la espera', async () => {
    mockRequestOtp.mockRejectedValue(new Error('Demasiados pedidos'))
    renderGate()
    await pedirCodigo()

    expect(screen.getByRole('button', { name: PEDIR })).not.toBeDisabled()
    expect(screen.queryByText(/Reenviar en/)).not.toBeInTheDocument()
  })

  it('durante la espera, un telefono verificado hace menos de 30 minutos entra directo', async () => {
    const onVerified = renderGate()
    await pedirCodigo('1155550101')
    fireEvent.click(screen.getByRole('button', { name: 'Cambiar teléfono o email' }))
    window.sessionStorage.setItem(
      'shifty:otp:sol',
      JSON.stringify({ phone: '1155550202', verifiedAt: new Date().toISOString() })
    )
    fireEvent.change(screen.getByLabelText('Teléfono'), { target: { value: '1155550202' } })

    fireEvent.click(screen.getByRole('button', { name: PEDIR }))

    expect(onVerified).toHaveBeenCalledWith('1155550202')
    expect(mockRequestOtp).toHaveBeenCalledTimes(1)
  })

  it('telefono y email se autocompletan y el codigo usa teclado numerico de 6 digitos', async () => {
    // 2026-09-30, F4-11: el codigo abria el teclado de letras y no se
    // ofrecia desde el mail; telefono y email no se autocompletaban.
    renderGate()
    expect(screen.getByLabelText('Teléfono')).toHaveAttribute('autocomplete', 'tel')
    expect(screen.getByLabelText('Tu email')).toHaveAttribute('autocomplete', 'email')

    await pedirCodigo()

    const codigo = screen.getByLabelText('Código')
    expect(codigo).toHaveAttribute('inputmode', 'numeric')
    expect(codigo).toHaveAttribute('autocomplete', 'one-time-code')
    expect(codigo).toHaveAttribute('maxlength', '6')
  })

  it('no muestra el debug_code aunque la API lo devuelva', async () => {
    // 2026-09-30, J7: con OTP_DEBUG_EXPOSE_CODE el backend devuelve un
    // senuelo cuando el codigo fue a un buzon distinto del tipeado.
    mockRequestOtp.mockResolvedValue({ ok: true, expires_at: '', debug_code: '424242' })
    renderGate()
    await pedirCodigo()

    expect(screen.getByLabelText('Código')).toBeInTheDocument()
    expect(screen.queryByText(/424242/)).not.toBeInTheDocument()
  })
})
