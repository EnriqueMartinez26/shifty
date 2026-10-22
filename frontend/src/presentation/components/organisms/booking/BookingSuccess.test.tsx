import React from 'react'

import { fireEvent, render, screen, within } from '@testing-library/react'

import type { BookingConfirmation } from '@application/services/PublicBookingService'

import { BookingSuccess } from './BookingSuccess'
import type { BookingWizardState } from './types'

const estado = (patch: Partial<BookingWizardState> = {}): BookingWizardState => ({
  serviceId: 'svc-1',
  extraServiceIds: [],
  requestedStaffId: null,
  assignedStaffId: 'st-1',
  assignedStaff: { name: 'Pro', isResource: false },
  date: '2026-09-25',
  startTime: '09:00',
  startsAt: '2026-09-25T12:00:00+00:00',
  // Con email: la reserva sin email tiene su propio bloque de tests.
  client: {
    name: 'Lucia',
    email: 'lucia@example.com',
    phone: '1155550101',
    notes: '',
    customFields: {}
  },
  promotionCode: '',
  promotionPreview: null,
  addons: [],
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
            confirmation: confirmacion({
              status: 'pending_payment',
              payment_required: true,
              payment_link: 'https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=1'
            })
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
        screen.getByText('Tu solicitud ya fue enviada y queda pendiente de confirmación.')
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

    it('muestra la fecha del turno como dd/MM/yyyy, no en ISO', () => {
      // 2026-10-02, QA en navegador: el resumen mostraba "2026-09-25".
      render(<BookingSuccess {...props()} />)

      expect(screen.getByText('25/09/2026')).toBeInTheDocument()
      expect(screen.queryByText('2026-09-25')).not.toBeInTheDocument()
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

    // 2026-10-02, QA en navegador: el WhatsApp de la tienda es texto libre.
    it('con un WhatsApp de la tienda que no se puede leer no ofrece coordinar', () => {
      render(<BookingSuccess {...props({ whatsappNumber: 'consultar en el local' })} />)

      expect(screen.queryByText(COORDINAR)).not.toBeInTheDocument()
    })

    // QA 2026-10-21: un turno confirmado sin seña ofrecia "Coordinar el pago".
    it.each([
      ['confirmada', 'confirmed'],
      ['pendiente de revision', 'pending']
    ])('%s sin seña no ofrece coordinar un pago que no existe', (_caso, status) => {
      render(
        <BookingSuccess
          {...props({
            whatsappNumber: '+54 9 11 5555-0000',
            confirmation: confirmacion({ status })
          })}
        />
      )

      expect(screen.queryByRole('link', { name: IR_A_PAGAR })).not.toBeInTheDocument()
      expect(screen.queryByRole('link', { name: COORDINAR })).not.toBeInTheDocument()
    })

    it('con seña requerida y sin link de pago ofrece coordinar por WhatsApp con la tienda', () => {
      render(
        <BookingSuccess
          {...props({
            whatsappNumber: '+54 9 11 5555-0000',
            // Una respuesta sin canal (backend anterior) con la seña pendiente.
            confirmation: confirmacion({ status: 'pending_payment', payment_required: true })
          })}
        />
      )

      expect(screen.queryByRole('link', { name: IR_A_PAGAR })).not.toBeInTheDocument()
      expect(screen.getByRole('link', { name: COORDINAR }).getAttribute('href')).toMatch(
        /^https:\/\/wa\.me\/5491155550000\?text=/
      )
    })

    // Decision de Mateo (2026-10-03): una sena obligatoria se paga por Mercado
    // Pago o por WhatsApp. QA 2026-10-02 (barberia-sentinel): la pantalla de
    // exito no mencionaba la sena cuando se pagaba por fuera.
    it('con sena por WhatsApp muestra el importe y el boton para coordinar el pago', () => {
      render(
        <BookingSuccess
          {...props({
            whatsappNumber: '11 5555 0303',
            confirmation: confirmacion({
              status: 'pending_payment',
              payment_required: true,
              deposit_channel: 'whatsapp',
              deposit_deadline: '2026-10-10T18:00:00+00:00',
              payment_link: null,
              payment_amount: 3000,
              payment_status: 'pending'
            })
          })}
        />
      )

      expect(screen.getByText('Reserva Pendiente de Pago')).toBeInTheDocument()
      expect(
        screen.getByText(
          'Pagá la seña por WhatsApp: tu turno se confirma cuando Tienda reciba el pago.'
        )
      ).toBeInTheDocument()
      expect(screen.getByText('Seña a pagar por WhatsApp')).toBeInTheDocument()
      expect(screen.getByText('$ 3.000')).toBeInTheDocument()
      // Decision de Mateo (2026-10-03): el cliente ve el plazo exacto, en hora
      // argentina (18:00 UTC son las 15:00).
      expect(
        screen.getByText(
          'Tenés hasta el sábado 10/10 a las 15:00 para pagar la seña por WhatsApp. Si no, el turno se libera.'
        )
      ).toBeInTheDocument()
      expect(screen.getByText('Estado: pendiente')).toBeInTheDocument()
      const boton = screen.getByRole('link', { name: COORDINAR })
      const href = boton.getAttribute('href') ?? ''
      expect(href).toMatch(/^https:\/\/wa\.me\/5491155550303\?text=/)
      // El mensaje ya le dice a la tienda que es para pagar la sena y cuanto
      // (Intl separa "$" del importe con un espacio duro).
      const texto = decodeURIComponent(href.split('text=')[1] ?? '').replace(/\s/g, ' ')
      expect(texto).toContain('Quiero pagar la seña de $ 3.000.')
      expect(screen.queryByRole('link', { name: IR_A_PAGAR })).not.toBeInTheDocument()
    })

    it('con sena por WhatsApp y sin numero que se pueda leer pide hablar con la tienda', () => {
      render(
        <BookingSuccess
          {...props({
            whatsappNumber: 'consultar en el local',
            confirmation: confirmacion({
              status: 'pending_payment',
              payment_required: true,
              deposit_channel: 'whatsapp',
              payment_amount: 3000
            })
          })}
        />
      )

      expect(screen.queryByRole('link', { name: COORDINAR })).not.toBeInTheDocument()
      expect(screen.getByText('Comunicate con Tienda para pagar la seña.')).toBeInTheDocument()
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
              deposit_channel: 'whatsapp',
              payment_amount: 3150,
              payment_status: 'pending'
            })
          })}
        />
      )

      expect(screen.getByText('Seña a pagar por WhatsApp')).toBeInTheDocument()
      expect(screen.getByText('$ 3.150')).toBeInTheDocument()
      // El estado en castellano: antes decia "Estado: pending".
      expect(screen.getByText('Estado: pendiente')).toBeInTheDocument()
      // Sin plazo en la respuesta no se inventa uno.
      expect(screen.queryByText(/Tenés hasta/)).not.toBeInTheDocument()
    })

    it('con link de pago muestra el pago requerido de Mercado Pago', () => {
      render(
        <BookingSuccess
          {...props({
            confirmation: confirmacion({
              status: 'pending_payment',
              payment_required: true,
              deposit_channel: 'mercadopago',
              deposit_deadline: '2026-10-10T18:00:00+00:00',
              payment_amount: 3150,
              payment_status: 'approved',
              payment_link: 'https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=1'
            })
          })}
        />
      )

      expect(screen.getByText('Pago requerido')).toBeInTheDocument()
      expect(screen.queryByText('Seña a pagar por WhatsApp')).not.toBeInTheDocument()
      // El plazo de WhatsApp no aplica al checkout de MP.
      expect(screen.queryByText(/Tenés hasta/)).not.toBeInTheDocument()
      expect(screen.getByText('Estado: aprobado')).toBeInTheDocument()
    })

    it('el canal sale de la respuesta: sin link y sin canal no es una sena por WhatsApp', () => {
      // Revision 4R de la PR #108 (R2): antes "pago requerido sin link" se
      // leia como sena por WhatsApp.
      render(
        <BookingSuccess
          {...props({
            confirmation: confirmacion({
              status: 'pending_payment',
              payment_required: true,
              deposit_channel: null,
              payment_amount: 3150
            })
          })}
        />
      )

      expect(screen.getByText('Pago requerido')).toBeInTheDocument()
      expect(screen.queryByText('Seña a pagar por WhatsApp')).not.toBeInTheDocument()
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
      expect(screen.queryByText('Seña a pagar por WhatsApp')).not.toBeInTheDocument()
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

describe('BookingSuccess: adicionales', () => {
  it('muestra cada adicional con su importe congelado y el total', () => {
    render(
      <BookingSuccess
        {...props({
          confirmation: confirmacion({
            service_price: 27000,
            final_price: 30000,
            addons_amount: 3000,
            addons: [
              { addon_id: 'strass', name: 'Strass', unit_price: 500, quantity: 6, amount: 3000 }
            ]
          })
        })}
      />
    )

    expect(screen.getByText(/Strass x6:/)).toHaveTextContent('3.000')
    expect(screen.getByText(/Total final:/)).toHaveTextContent('30.000')
  })
})

// S5 (2026-10-21): el detalle completo pasa del paso de confirmacion a esta
// pantalla, con el profesional que antes faltaba.
describe('BookingSuccess: detalle completo del turno', () => {
  const detalle = () => screen.getByRole('region', { name: 'Detalles del Turno' })

  it('muestra profesional, servicios, adicionales, total y la seña pendiente', () => {
    render(
      <BookingSuccess
        {...props({
          confirmation: confirmacion({
            status: 'pending_payment',
            staff_name: 'Natalia',
            service_name: 'Semipermanente',
            service_price: 20000,
            final_price: 23000,
            addons_amount: 3000,
            addons: [
              { addon_id: 'deco', name: 'Decoración', unit_price: 1000, quantity: 3, amount: 3000 }
            ],
            payment_required: true,
            deposit_channel: 'whatsapp',
            payment_amount: 6900,
            payment_status: 'pending'
          })
        })}
      />
    )

    expect(within(detalle()).getByText('Profesional')).toBeInTheDocument()
    expect(within(detalle()).getByText('Natalia')).toBeInTheDocument()
    expect(within(detalle()).getByText('Semipermanente')).toBeInTheDocument()
    expect(within(detalle()).getByText(/Decoración x3:/)).toHaveTextContent('3.000')
    expect(within(detalle()).getByText(/Total final:/)).toHaveTextContent('23.000')
    expect(within(detalle()).getByText('Seña a pagar por WhatsApp')).toBeInTheDocument()
    expect(within(detalle()).getByText(/6\.900/)).toBeInTheDocument()
    expect(within(detalle()).getByText('Estado: pendiente')).toBeInTheDocument()
  })

  it('una cancha o sala no se presenta como profesional', () => {
    render(
      <BookingSuccess
        {...props({
          bookingState: estado({ assignedStaff: { name: 'Cancha 1', isResource: true } }),
          confirmation: confirmacion({ staff_name: 'Cancha 1' })
        })}
      />
    )

    expect(within(detalle()).getByText('Cancha / sala')).toBeInTheDocument()
    expect(within(detalle()).getByText('Cancha 1')).toBeInTheDocument()
    expect(within(detalle()).queryByText('Profesional')).not.toBeInTheDocument()
  })

  it('sin el nombre de quien atiende no lo inventa', () => {
    render(
      <BookingSuccess
        {...props({
          bookingState: estado({ assignedStaff: null }),
          confirmation: confirmacion({ staff_name: '  ' })
        })}
      />
    )

    expect(within(detalle()).queryByText('Profesional')).not.toBeInTheDocument()
  })
})

describe('BookingSuccess: reserva sin email', () => {
  const sinEmail = estado({
    client: { name: 'Lucia', email: '  ', phone: '1155550101', notes: '', customFields: {} }
  })
  // 18:00 UTC = 15:00 en Argentina, viernes 23/10/2026.
  const turno = confirmacion({
    public_id: 'apt-77',
    staff_name: 'Natalia',
    starts_at: '2026-10-23T18:00:00Z',
    ends_at: '2026-10-23T18:30:00Z'
  })
  const AVISO =
    'Como no dejaste email, no te vamos a mandar recordatorios. Guardalo en tu calendario o mandátelo por WhatsApp.'

  it('confirmada: titulo, cuando y con quien, aviso y sin "mis turnos"', () => {
    render(<BookingSuccess {...props({ bookingState: sinEmail, confirmation: turno })} />)

    expect(screen.getByRole('heading', { name: 'Turno reservado' })).toBeInTheDocument()
    expect(
      screen.getByText('Turno reservado para el viernes 23/10 a las 15:00 con Natalia.')
    ).toBeInTheDocument()
    expect(screen.getByRole('note')).toHaveTextContent(AVISO)
    expect(screen.queryByText(/Te enviamos los detalles/)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: MIS_TURNOS })).not.toBeInTheDocument()
  })

  it('pendiente de confirmacion se anuncia como reserva registrada', () => {
    render(
      <BookingSuccess
        {...props({ bookingState: sinEmail, confirmation: { ...turno, status: 'pending' } })}
      />
    )

    expect(screen.getByRole('heading', { name: 'Reserva registrada' })).toBeInTheDocument()
    expect(
      screen.getByText('Tu solicitud ya fue enviada y queda pendiente de confirmación.')
    ).toBeInTheDocument()
  })

  it('agregar al calendario descarga el .ics del turno', () => {
    jest.useFakeTimers()
    const create = jest.fn((_blob: Blob) => 'blob:turno')
    const originalCreate = window.URL.createObjectURL
    const originalRevoke = window.URL.revokeObjectURL
    window.URL.createObjectURL = create
    window.URL.revokeObjectURL = jest.fn()
    const click = jest.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})

    render(<BookingSuccess {...props({ bookingState: sinEmail, confirmation: turno })} />)
    fireEvent.click(screen.getByRole('button', { name: 'Agregar al calendario' }))

    expect(create).toHaveBeenCalledTimes(1)
    const link = click.mock.instances[0] as unknown as HTMLAnchorElement
    expect(link.download).toBe('turno-apt-77.ics')
    jest.runOnlyPendingTimers()
    jest.useRealTimers()
    click.mockRestore()
    window.URL.createObjectURL = originalCreate
    window.URL.revokeObjectURL = originalRevoke
  })

  it('mandarselo por WhatsApp comparte el turno, el servicio y la tienda', () => {
    render(<BookingSuccess {...props({ bookingState: sinEmail, confirmation: turno })} />)

    const href = screen.getByRole('link', { name: 'Mandármelo por WhatsApp' }).getAttribute('href')
    expect(href).toMatch(/^https:\/\/wa\.me\/\?text=/)
    const texto = decodeURIComponent((href ?? '').split('?text=')[1] ?? '')
    expect(texto).toContain('Turno reservado para el viernes 23/10 a las 15:00 con Natalia.')
    expect(texto).toContain('Servicio: Corte')
    expect(texto).toContain('Lugar: Tienda')
  })

  it('con WhatsApp de la tienda ofrece escribirle para cambiarlo o cancelarlo', () => {
    render(
      <BookingSuccess
        {...props({ bookingState: sinEmail, confirmation: turno, whatsappNumber: '11 5555 0303' })}
      />
    )

    const href = screen
      .getByRole('link', { name: 'Escribirle a Tienda por WhatsApp' })
      .getAttribute('href')
    expect(href).toMatch(/^https:\/\/wa\.me\/5491155550303\?text=/)
    expect(decodeURIComponent((href ?? '').split('?text=')[1] ?? '')).toBe(
      'Hola, reservé el turno apt-77 para el viernes 23/10 a las 15:00. Quiero cambiarlo/cancelarlo.'
    )
  })

  it('sin WhatsApp de la tienda pide comunicarse con ella', () => {
    render(<BookingSuccess {...props({ bookingState: sinEmail, confirmation: turno })} />)

    expect(
      screen.queryByRole('link', { name: 'Escribirle a Tienda por WhatsApp' })
    ).not.toBeInTheDocument()
    expect(
      screen.getByText('Para cambiarlo o cancelarlo, comunicate con Tienda.')
    ).toBeInTheDocument()
  })

  it('con sena por WhatsApp mantiene el flujo de pago', () => {
    render(
      <BookingSuccess
        {...props({
          bookingState: sinEmail,
          whatsappNumber: '11 5555 0303',
          confirmation: {
            ...turno,
            status: 'pending_payment',
            payment_required: true,
            deposit_channel: 'whatsapp',
            payment_amount: 3000
          }
        })}
      />
    )

    expect(screen.getByRole('heading', { name: 'Reserva registrada' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: COORDINAR })).toBeInTheDocument()
    expect(screen.getByText('Seña a pagar por WhatsApp')).toBeInTheDocument()
  })
})

describe('BookingSuccess: diseño previo (S7)', () => {
  const ENVIAR = 'Enviar mi diseño por WhatsApp'
  const DEFAULT = 'Mandale tu diseño a Tienda por WhatsApp para que lo vea antes del turno.'
  const conDiseno = [{ requires_prior_design: true, prior_design_message: null }]
  // 18:00 UTC = 15:00 en Argentina, viernes 23/10/2026.
  const turno = confirmacion({
    public_id: 'apt-77',
    starts_at: '2026-10-23T18:00:00Z',
    ends_at: '2026-10-23T18:30:00Z'
  })
  const sinEmail = estado({
    client: { name: 'Lucia', email: '', phone: '1155550101', notes: '', customFields: {} }
  })

  it('sin un servicio con la opcion no muestra nada nuevo', () => {
    render(<BookingSuccess {...props({ whatsappNumber: '11 5555 0303' })} />)

    expect(screen.queryByRole('link', { name: ENVIAR })).not.toBeInTheDocument()
    expect(screen.queryByText(DEFAULT)).not.toBeInTheDocument()
  })

  it('confirmada sin seña: mensaje y boton con el turno en hora argentina', () => {
    render(
      <BookingSuccess
        {...props({
          confirmation: turno,
          whatsappNumber: '11 5555 0303',
          bookedServices: conDiseno
        })}
      />
    )

    expect(screen.getByText('Reserva Confirmada')).toBeInTheDocument()
    expect(screen.getByText(DEFAULT)).toBeInTheDocument()
    const href = screen.getByRole('link', { name: ENVIAR }).getAttribute('href') ?? ''
    expect(href).toMatch(/^https:\/\/wa\.me\/5491155550303\?text=/)
    expect(decodeURIComponent(href.split('?text=')[1] ?? '')).toBe(
      [
        'Hola Tienda, soy Lucia.',
        'Reservé Corte para el viernes 23/10 a las 15:00 (turno apt-77).',
        'Te mando mi diseño para que lo veas antes del turno.'
      ].join('\n')
    )
  })

  it('con seña por Mercado Pago pendiente lo muestra junto a "Ir a pagar"', () => {
    render(
      <BookingSuccess
        {...props({
          whatsappNumber: '11 5555 0303',
          bookedServices: conDiseno,
          confirmation: {
            ...turno,
            status: 'pending_payment',
            payment_required: true,
            payment_link: 'https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=1'
          }
        })}
      />
    )

    expect(screen.getByRole('link', { name: /Ir a pagar/ })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: ENVIAR })).toBeInTheDocument()
  })

  it('con seña por WhatsApp mantiene el boton de pago y suma el del diseño', () => {
    render(
      <BookingSuccess
        {...props({
          whatsappNumber: '11 5555 0303',
          bookedServices: conDiseno,
          confirmation: {
            ...turno,
            status: 'pending_payment',
            payment_required: true,
            deposit_channel: 'whatsapp',
            payment_amount: 3000
          }
        })}
      />
    )

    expect(screen.getByRole('link', { name: COORDINAR })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: ENVIAR })).toBeInTheDocument()
  })

  it('sin email tambien lo muestra', () => {
    render(
      <BookingSuccess
        {...props({
          bookingState: sinEmail,
          confirmation: turno,
          whatsappNumber: '11 5555 0303',
          bookedServices: conDiseno
        })}
      />
    )

    expect(screen.getByText('Turno reservado')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: ENVIAR })).toBeInTheDocument()
  })

  it('sin un WhatsApp confiable muestra el mensaje sin el boton', () => {
    render(
      <BookingSuccess
        {...props({ confirmation: turno, whatsappNumber: null, bookedServices: conDiseno })}
      />
    )

    expect(screen.getByText(DEFAULT)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: ENVIAR })).not.toBeInTheDocument()
  })
})

// S9 (2026-10-22): el titulo y los iconos del detalle eran un tono oscurecido
// del color de la tienda (amarillo a oliva). Ahora son texto neutro; la marca
// queda solo en el relleno del boton principal.
describe('BookingSuccess sin tonos de marca en el texto', () => {
  it('ningun texto ni icono usa una variable de marca salvo el texto sobre el relleno', () => {
    const { container } = render(<BookingSuccess {...props({ whatsappNumber: '351 555-1234' })} />)

    const teñidos = Array.from(container.querySelectorAll<HTMLElement>('[style]'))
      .map((el) => el.style.color)
      .filter((color) => color.includes('--brand-') && !color.includes('--brand-on-fill'))
    expect(teñidos).toEqual([])
    expect(screen.getAllByRole('heading', { level: 2 })[0]?.style.color).toBe('rgb(64, 64, 64)')
  })
})
