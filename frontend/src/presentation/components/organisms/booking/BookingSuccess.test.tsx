import React from 'react'

import { render, screen } from '@testing-library/react'

import type { BookingConfirmation } from '@application/services/PublicBookingService'

import { BookingSuccess } from './BookingSuccess'
import type { BookingWizardState } from './types'

const estado = (patch: Partial<BookingWizardState> = {}): BookingWizardState => ({
  serviceId: 'svc-1',
  requestedStaffId: null,
  assignedStaffId: 'st-1',
  date: '2026-09-25',
  startTime: '09:00',
  startsAt: '2026-09-25T12:00:00+00:00',
  client: { name: 'Lucia', email: '', phone: '1155550101', notes: '', customFields: {} },
  promotionCode: '',
  ...patch
})

const confirmacion = (patch: Partial<BookingConfirmation> = {}): BookingConfirmation => ({
  public_id: 'apt-1',
  service_id: 'svc-1',
  service_name: 'Corte',
  staff_id: 'st-1',
  staff_name: 'Pro',
  starts_at: '2026-09-25T12:00:00+00:00',
  ends_at: '2026-09-25T12:30:00+00:00',
  status: 'confirmed',
  client_name: 'Lucia',
  client_phone: '1155550101',
  payment_required: false,
  ...patch
})

type Props = React.ComponentProps<typeof BookingSuccess>

const props = (patch: Partial<Props> = {}): Props => ({
  confirmation: confirmacion(),
  bookingState: estado(),
  storeSlug: 'tienda',
  storeName: 'Tienda',
  whatsappNumber: null,
  ...patch
})

const IR_A_PAGAR = 'Ir a pagar'
const COORDINAR = 'Coordinar el pago por WhatsApp'
const MIS_TURNOS = 'Quiero cambiar o cancelar mi turno'

describe('BookingSuccess', () => {
  describe('titulo segun el estado del turno', () => {
    it('con pago pendiente anuncia la reserva pendiente de pago', () => {
      render(
        <BookingSuccess
          {...props({
            confirmation: confirmacion({ status: 'pending_payment', payment_required: true })
          })}
        />
      )

      expect(screen.getByText('Reserva Pendiente de Pago')).toBeInTheDocument()
      expect(
        screen.getByText('Tu turno se confirma cuando el cobro quede aprobado.')
      ).toBeInTheDocument()
    })

    it('pendiente de revision anuncia la reserva registrada', () => {
      render(<BookingSuccess {...props({ confirmation: confirmacion({ status: 'pending' }) })} />)

      expect(screen.getByText('Reserva Registrada')).toBeInTheDocument()
      expect(
        screen.getByText('Tu solicitud ya fue enviada y queda pendiente de confirmacion.')
      ).toBeInTheDocument()
    })

    it('confirmada anuncia la reserva confirmada con el email del cliente', () => {
      render(
        <BookingSuccess
          {...props({
            bookingState: estado({
              client: {
                name: 'Lucia',
                email: 'lucia@example.com',
                phone: '1155550101',
                notes: '',
                customFields: {}
              }
            })
          })}
        />
      )

      expect(screen.getByText('Reserva Confirmada')).toBeInTheDocument()
      expect(screen.getByText('Te enviamos los detalles a lucia@example.com')).toBeInTheDocument()
    })
  })

  describe('pago', () => {
    it('con link de pago ofrece ir a pagar y no coordinar por WhatsApp', () => {
      render(
        <BookingSuccess
          {...props({
            whatsappNumber: '+54 9 11 5555-0000',
            confirmation: confirmacion({
              status: 'pending_payment',
              payment_required: true,
              payment_link: 'https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=1'
            })
          })}
        />
      )

      expect(screen.getByRole('link', { name: IR_A_PAGAR })).toHaveAttribute(
        'href',
        'https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=1'
      )
      expect(screen.queryByRole('link', { name: COORDINAR })).not.toBeInTheDocument()
    })

    it('sin link de pago ofrece coordinar por WhatsApp con el numero de la tienda', () => {
      render(<BookingSuccess {...props({ whatsappNumber: '+54 9 11 5555-0000' })} />)

      expect(screen.queryByRole('link', { name: IR_A_PAGAR })).not.toBeInTheDocument()
      expect(screen.getByRole('link', { name: COORDINAR }).getAttribute('href')).toMatch(
        /^https:\/\/wa\.me\/5491155550000\?text=/
      )
    })

    it('sin link y sin WhatsApp de la tienda no ofrece coordinar', () => {
      render(<BookingSuccess {...props()} />)

      expect(screen.queryByRole('link', { name: COORDINAR })).not.toBeInTheDocument()
    })
  })

  describe('resumen de precio y pago requerido', () => {
    // 2026-10-02: el resumen comercial y el bloque de pago requerido no tenian
    // test; un cambio en los importes o en la condicion de mostrarlos pasaba
    // sin que nada fallara.
    it('muestra servicio, descuento y total con sus importes', () => {
      render(
        <BookingSuccess
          {...props({
            confirmation: confirmacion({
              service_price: 12000,
              discount_amount: 1500,
              final_price: 10500
            })
          })}
        />
      )

      expect(screen.getByText('Resumen comercial')).toBeInTheDocument()
      expect(screen.getByText('Servicio: $ 12.000')).toBeInTheDocument()
      expect(screen.getByText('Descuento: -$ 1.500')).toBeInTheDocument()
      expect(screen.getByText('Total final: $ 10.500')).toBeInTheDocument()
    })

    it('sin descuento no muestra la linea y el total cae al precio del servicio', () => {
      render(
        <BookingSuccess
          {...props({
            confirmation: confirmacion({ service_price: 12000, discount_amount: 0 })
          })}
        />
      )

      expect(screen.getByText('Servicio: $ 12.000')).toBeInTheDocument()
      expect(screen.queryByText(/Descuento:/)).not.toBeInTheDocument()
      expect(screen.getByText('Total final: $ 12.000')).toBeInTheDocument()
    })

    it('sin precio no muestra el resumen comercial', () => {
      render(<BookingSuccess {...props()} />)

      expect(screen.queryByText('Resumen comercial')).not.toBeInTheDocument()
    })

    it('con pago requerido muestra la sena a pagar y su estado', () => {
      render(
        <BookingSuccess
          {...props({
            confirmation: confirmacion({
              status: 'pending_payment',
              payment_required: true,
              payment_amount: 3150,
              payment_status: 'pending'
            })
          })}
        />
      )

      expect(screen.getByText('Pago requerido')).toBeInTheDocument()
      expect(screen.getByText('$ 3.150')).toBeInTheDocument()
      expect(screen.getByText('Estado: pending')).toBeInTheDocument()
    })

    it('con pago requerido sin importe ni estado avisa que el importe se confirma', () => {
      render(
        <BookingSuccess
          {...props({
            confirmation: confirmacion({ status: 'pending_payment', payment_required: true })
          })}
        />
      )

      expect(screen.getByText('Importe a confirmar')).toBeInTheDocument()
      expect(screen.getByText('Estado: pendiente')).toBeInTheDocument()
    })

    it('sin pago requerido no muestra el bloque aunque traiga importe', () => {
      render(
        <BookingSuccess
          {...props({
            confirmation: confirmacion({ payment_required: false, payment_amount: 3150 })
          })}
        />
      )

      expect(screen.queryByText('Pago requerido')).not.toBeInTheDocument()
      expect(screen.queryByText('$ 3.150')).not.toBeInTheDocument()
    })
  })

  describe('mis turnos', () => {
    it('con el slug de la tienda ofrece cambiar o cancelar el turno', () => {
      render(<BookingSuccess {...props()} />)

      expect(screen.getByRole('link', { name: MIS_TURNOS })).toHaveAttribute(
        'href',
        '/b/tienda/mis-turnos'
      )
    })

    it('sin slug no ofrece cambiar o cancelar el turno', () => {
      render(<BookingSuccess {...props({ storeSlug: undefined })} />)

      expect(screen.queryByRole('link', { name: MIS_TURNOS })).not.toBeInTheDocument()
    })
  })
})
