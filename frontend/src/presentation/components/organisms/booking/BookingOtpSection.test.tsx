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
  debugCode: '',
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

const CODIGO = 'Código que te llegó por email'

describe('BookingOtpSection', () => {
  it('anuncia la verificacion del telefono que se tipeo', () => {
    render(<BookingOtpSection {...props()} />)

    expect(screen.getByText('Verificamos tu teléfono')).toBeInTheDocument()
    expect(
      screen.getByText('Te mandamos un código por email para confirmar el 1155550101')
    ).toBeInTheDocument()
  })

  it('el codigo usa teclado numerico, autocompletado de codigo y 6 digitos', () => {
    render(<BookingOtpSection {...props()} />)

    const codigo = screen.getByPlaceholderText(CODIGO)
    expect(codigo).toHaveAttribute('inputmode', 'numeric')
    expect(codigo).toHaveAttribute('autocomplete', 'one-time-code')
    expect(codigo).toHaveAttribute('maxlength', '6')
    const email = screen.getByLabelText('Email para el código')
    expect(email).toHaveAttribute('inputmode', 'email')
    expect(email).toHaveAttribute('autocomplete', 'email')
  })

  describe('pedir el codigo', () => {
    it('enviar codigo llama a onRequestOtp', () => {
      const onRequestOtp = jest.fn()
      render(<BookingOtpSection {...props({ onRequestOtp })} />)

      fireEvent.click(screen.getByRole('button', { name: 'Enviar código' }))

      expect(onRequestOtp).toHaveBeenCalledTimes(1)
    })

    it('sin email no deja pedir el codigo', () => {
      render(<BookingOtpSection {...props({ otpState: otpInicial({ email: '  ' }) })} />)

      expect(screen.getByRole('button', { name: 'Enviar código' })).toBeDisabled()
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

      const boton = screen.getByRole('button', { name: 'Enviar código' })
      expect(boton).toBeDisabled()
      fireEvent.click(boton)
      expect(onRequestOtp).not.toHaveBeenCalled()
      expect(screen.getByRole('alert')).toHaveTextContent(aviso)
    })
  })

  describe('verificar el codigo', () => {
    it('sin codigo no deja verificar', () => {
      render(<BookingOtpSection {...props()} />)

      expect(screen.getByRole('button', { name: 'Verificar código' })).toBeDisabled()
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

      fireEvent.click(screen.getByRole('button', { name: 'Verificar código' }))

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

      expect(screen.getByText('Teléfono validado correctamente')).toBeInTheDocument()
      expect(screen.queryByRole('button', { name: 'Verificar código' })).not.toBeInTheDocument()
    })
  })

  describe('los campos avisan lo que se tipea', () => {
    it('el email se pasa tal cual a onOtpEmailChange', () => {
      const onOtpEmailChange = jest.fn()
      render(<BookingOtpSection {...props({ onOtpEmailChange })} />)

      fireEvent.change(screen.getByLabelText('Email para el código'), {
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

  describe('codigo debug (J7)', () => {
    // 2026-09-30, J7: mostrar el codigo debug con aviso de que puede no servir.
    // Con OTP_DEBUG_EXPOSE_CODE el backend devuelve el codigo real solo si fue
    // al email tipeado; si fue al email de la ficha devuelve un senuelo
    // (AUD2-SYNC-01). La seccion muestra el valor tal cual y lo avisa.
    it('con debugCode muestra el codigo con el aviso exacto', () => {
      render(
        <BookingOtpSection
          {...props({ otpState: otpInicial({ email: 'lucia@example.com', debugCode: '424242' }) })}
        />
      )

      expect(screen.getByRole('status')).toHaveTextContent(
        'Código debug (solo desarrollo): 424242. Si el teléfono ya tiene ficha con email, el código real fue a ese buzón y este puede no servir.'
      )
      // Se muestra, no se autocompleta: el codigo lo tipea la persona.
      expect((screen.getByPlaceholderText(CODIGO) as HTMLInputElement).value).toBe('')
    })

    it('sin debugCode no muestra nada', () => {
      render(<BookingOtpSection {...props()} />)

      expect(screen.queryByRole('status')).not.toBeInTheDocument()
      expect(screen.queryByText(/Código debug/)).not.toBeInTheDocument()
    })
  })
})
