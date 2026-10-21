import React from 'react'

import { render, screen } from '@testing-library/react'

import type { BookingConfirmation } from '@application/services/PublicBookingService'

import { BookingPriorDesign } from './BookingPriorDesign'

// S7 (Mateo): "le sale una redireccion al numero de natalia para enviar el
// diseño junto con el turno respectivo asi natalia lo confirma desde la pagina".
// El cobro no cambia: este bloque es solo el aviso y el boton.

const confirmacion = (patch: Partial<BookingConfirmation> = {}): BookingConfirmation => ({
  public_id: 'apt-9',
  service_id: 'svc-1',
  service_name: 'Uñas esculpidas',
  staff_id: 'st-1',
  staff_name: 'Natalia',
  starts_at: '2026-10-23T18:00:00+00:00',
  ends_at: '2026-10-23T19:00:00+00:00',
  status: 'confirmed',
  client_name: 'Lucia',
  client_phone: '1155550101',
  payment_required: false,
  ...patch
})

type Props = React.ComponentProps<typeof BookingPriorDesign>

const props = (patch: Partial<Props> = {}): Props => ({
  services: [{ requires_prior_design: true, prior_design_message: null }],
  confirmation: confirmacion(),
  clientName: 'Lucia',
  when: 'viernes 23/10 a las 15:00',
  storeName: 'Natalia Nails',
  whatsappNumber: '11 5555 0303',
  ...patch
})

const BOTON = 'Enviar mi diseño por WhatsApp'
const DEFAULT = 'Mandale tu diseño a Natalia Nails por WhatsApp para que lo vea antes del turno.'

const textoDelLink = () => {
  const href = screen.getByRole('link', { name: BOTON }).getAttribute('href') ?? ''
  return { href, texto: decodeURIComponent(href.split('?text=')[1] ?? '') }
}

describe('BookingPriorDesign', () => {
  it.each([
    ['sin servicios', []],
    ['un servicio sin la opcion', [{ requires_prior_design: false, prior_design_message: null }]],
    // El backend guarda el mensaje aunque la opcion este apagada: no se muestra.
    [
      'la opcion apagada con un mensaje guardado',
      [{ requires_prior_design: false, prior_design_message: 'Traé tu diseño' }]
    ],
    // Un backend anterior al diseño previo no manda el campo: es "no".
    ['un backend que no manda el campo', [{}]]
  ])('%s no muestra nada', (_caso, services) => {
    const { container } = render(<BookingPriorDesign {...props({ services })} />)

    expect(container.innerHTML).toBe('')
  })

  it('con el servicio principal marcado muestra el mensaje por defecto y el boton', () => {
    render(<BookingPriorDesign {...props()} />)

    expect(screen.getByText(DEFAULT)).toBeInTheDocument()
    const link = screen.getByRole('link', { name: BOTON })
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer')
    expect(link).toHaveClass('min-h-[44px]')
    // QA 2026-10-21: en 360 px la etiqueta corta en dos lineas y quedaba a la izquierda.
    expect(link).toHaveClass('text-center')
    expect(textoDelLink().href).toMatch(/^https:\/\/wa\.me\/5491155550303\?text=/)
  })

  it('con un servicio sumado marcado tambien lo muestra', () => {
    render(
      <BookingPriorDesign
        {...props({
          services: [
            { requires_prior_design: false, prior_design_message: null },
            { requires_prior_design: true, prior_design_message: null }
          ]
        })}
      />
    )

    expect(screen.getByText(DEFAULT)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: BOTON })).toBeInTheDocument()
  })

  it('usa el mensaje de la tienda cuando lo escribio', () => {
    render(
      <BookingPriorDesign
        {...props({
          services: [
            { requires_prior_design: false, prior_design_message: 'Este no' },
            { requires_prior_design: true, prior_design_message: '  Mandame una foto  ' }
          ]
        })}
      />
    )

    expect(screen.getByText('Mandame una foto')).toBeInTheDocument()
    expect(screen.queryByText(DEFAULT)).not.toBeInTheDocument()
    expect(screen.queryByText('Este no')).not.toBeInTheDocument()
  })

  it('el texto de WhatsApp identifica el turno: nombre, servicios, adicionales, dia y hora', () => {
    render(
      <BookingPriorDesign
        {...props({
          confirmation: confirmacion({
            services_label: 'Uñas esculpidas + Kapping',
            addons: [
              {
                addon_id: 'strass',
                name: 'Strass',
                unit_price: 500,
                quantity: 6,
                amount: 3000
              }
            ]
          })
        })}
      />
    )

    expect(textoDelLink().texto).toBe(
      [
        'Hola Natalia Nails, soy Lucia.',
        'Reservé Uñas esculpidas + Kapping (Strass x6) para el viernes 23/10 a las 15:00 (turno apt-9).',
        'Te mando mi diseño para que lo veas antes del turno.'
      ].join('\n')
    )
  })

  it('sin adicionales ni nombre no los inventa', () => {
    render(<BookingPriorDesign {...props({ clientName: '  ' })} />)

    expect(textoDelLink().texto).toBe(
      [
        'Hola Natalia Nails.',
        'Reservé Uñas esculpidas para el viernes 23/10 a las 15:00 (turno apt-9).',
        'Te mando mi diseño para que lo veas antes del turno.'
      ].join('\n')
    )
  })

  it.each([
    ['sin numero', null],
    ['con un numero que no es confiable', 'consultar en el local']
  ])('%s muestra el mensaje sin el boton', (_caso, whatsappNumber) => {
    render(<BookingPriorDesign {...props({ whatsappNumber })} />)

    expect(screen.getByText(DEFAULT)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: BOTON })).not.toBeInTheDocument()
  })
})
