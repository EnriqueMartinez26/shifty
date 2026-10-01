import { fireEvent, render, screen, waitFor } from '@testing-library/react'

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
