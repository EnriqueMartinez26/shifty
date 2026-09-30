import React from 'react'

import { fireEvent, render, screen } from '@testing-library/react'

import { BookingOtpSection } from './BookingOtpSection'
import type { BookingOtpState } from './types'

const otpInicial = (patch: Partial<BookingOtpState> = {}): BookingOtpState => ({
  code: '',
  channel: 'email',
  email: '',
  verified: false,
  verifiedPhone: '',
  expiresAt: '',
  error: '',
  rateLimited: false,
  ...patch
})

type Props = React.ComponentProps<typeof BookingOtpSection>

const props = (patch: Partial<Props> = {}): Props => ({
  phone: '1155550101',
  otpState: otpInicial({ email: 'lucia@example.com' }),
  isRequestingOtp: false,
  otpResendSeconds: 0,
  isVerifyingOtp: false,
  onRequestOtp: jest.fn(),
  onVerifyOtp: jest.fn(),
  onOtpEmailChange: jest.fn(),
  onOtpCodeChange: jest.fn(),
  ...patch
})

const CODIGO = 'Codigo que te llego por email'

describe('BookingOtpSection', () => {
  it('anuncia la verificacion del telefono que se tipeo', () => {
    render(<BookingOtpSection {...props()} />)

    expect(screen.getByText('Verificamos tu telefono')).toBeInTheDocument()
    expect(
      screen.getByText('Te mandamos un codigo por email para confirmar el 1155550101')
    ).toBeInTheDocument()
  })

  it('el codigo usa teclado numerico, autocompletado de codigo y 6 digitos', () => {
    render(<BookingOtpSection {...props()} />)

    const codigo = screen.getByPlaceholderText(CODIGO)
    expect(codigo).toHaveAttribute('inputmode', 'numeric')
    expect(codigo).toHaveAttribute('autocomplete', 'one-time-code')
    expect(codigo).toHaveAttribute('maxlength', '6')
    const email = screen.getByLabelText('Email para el codigo')
    expect(email).toHaveAttribute('inputmode', 'email')
    expect(email).toHaveAttribute('autocomplete', 'email')
  })

  describe('pedir el codigo', () => {
    it('enviar codigo llama a onRequestOtp', () => {
      const onRequestOtp = jest.fn()
      render(<BookingOtpSection {...props({ onRequestOtp })} />)

      fireEvent.click(screen.getByRole('button', { name: 'Enviar codigo' }))

      expect(onRequestOtp).toHaveBeenCalledTimes(1)
    })

    it('sin email no deja pedir el codigo', () => {
      render(<BookingOtpSection {...props({ otpState: otpInicial({ email: '  ' }) })} />)

      expect(screen.getByRole('button', { name: 'Enviar codigo' })).toBeDisabled()
    })

    it('mientras se envia muestra Enviando... y no pide otro', () => {
      render(<BookingOtpSection {...props({ isRequestingOtp: true })} />)

      expect(screen.getByRole('button', { name: 'Enviando...' })).toBeDisabled()
    })

    it('durante la espera el boton muestra los segundos y no pide', () => {
      const onRequestOtp = jest.fn()
      render(<BookingOtpSection {...props({ onRequestOtp, otpResendSeconds: 42 })} />)

      const boton = screen.getByRole('button', { name: 'Reenviar en 42 s' })
      expect(boton).toBeDisabled()
      fireEvent.click(boton)
      expect(onRequestOtp).not.toHaveBeenCalled()
    })

    it('con OTP_RATE_LIMITED no deja pedir otro codigo y muestra el aviso', () => {
      const aviso =
        'Pediste demasiados códigos para este teléfono. Esperá un rato antes de pedir otro.'
      const onRequestOtp = jest.fn()
      render(
        <BookingOtpSection
          {...props({
            onRequestOtp,
            otpState: otpInicial({ email: 'lucia@example.com', rateLimited: true, error: aviso })
          })}
        />
      )

      const boton = screen.getByRole('button', { name: 'Enviar codigo' })
      expect(boton).toBeDisabled()
      fireEvent.click(boton)
      expect(onRequestOtp).not.toHaveBeenCalled()
      expect(screen.getByRole('alert')).toHaveTextContent(aviso)
    })
  })

  describe('verificar el codigo', () => {
    it('sin codigo no deja verificar', () => {
      render(<BookingOtpSection {...props()} />)

      expect(screen.getByRole('button', { name: 'Verificar codigo' })).toBeDisabled()
    })

    it('con codigo verificar llama a onVerifyOtp', () => {
      const onVerifyOtp = jest.fn()
      render(
        <BookingOtpSection
          {...props({
            onVerifyOtp,
            otpState: otpInicial({ email: 'lucia@example.com', code: '123456' })
          })}
        />
      )

      fireEvent.click(screen.getByRole('button', { name: 'Verificar codigo' }))

      expect(onVerifyOtp).toHaveBeenCalledTimes(1)
    })

    it('mientras verifica muestra Verificando... y no verifica otra vez', () => {
      render(
        <BookingOtpSection
          {...props({
            isVerifyingOtp: true,
            otpState: otpInicial({ email: 'lucia@example.com', code: '123456' })
          })}
        />
      )

      expect(screen.getByRole('button', { name: 'Verificando...' })).toBeDisabled()
    })

    it('verificado muestra el telefono validado en lugar del boton', () => {
      render(
        <BookingOtpSection
          {...props({ otpState: otpInicial({ verified: true, verifiedPhone: '+1155550101' }) })}
        />
      )

      expect(screen.getByText('Telefono validado correctamente')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Verificar codigo' })).not.toBeInTheDocument()
    })
  })

  describe('los campos avisan lo que se tipea', () => {
    it('el email se pasa tal cual a onOtpEmailChange', () => {
      const onOtpEmailChange = jest.fn()
      render(<BookingOtpSection {...props({ onOtpEmailChange })} />)

      fireEvent.change(screen.getByLabelText('Email para el codigo'), {
        target: { value: 'otra@example.com' }
      })

      expect(onOtpEmailChange).toHaveBeenLastCalledWith('otra@example.com')
    })

    it('el codigo descarta lo que no es un digito', () => {
      const onOtpCodeChange = jest.fn()
      render(<BookingOtpSection {...props({ onOtpCodeChange })} />)

      fireEvent.change(screen.getByPlaceholderText(CODIGO), { target: { value: '12a-3 4' } })

      expect(onOtpCodeChange).toHaveBeenLastCalledWith('1234')
    })
  })

  it('no muestra el debug_code aunque llegue en el estado (J7)', () => {
    // J7 (2026-09-30): con OTP_DEBUG_EXPOSE_CODE el backend puede devolver el
    // codigo; la seccion no tiene donde mostrarlo y no lo muestra.
    const conDebug = { ...otpInicial({ email: 'lucia@example.com' }), debug_code: '424242' }
    render(<BookingOtpSection {...props({ otpState: conDebug })} />)

    expect(screen.queryByText(/424242/)).not.toBeInTheDocument()
    expect((screen.getByPlaceholderText(CODIGO) as HTMLInputElement).value).toBe('')
    expect((screen.getByLabelText('Email para el codigo') as HTMLInputElement).value).toBe(
      'lucia@example.com'
    )
  })
})
