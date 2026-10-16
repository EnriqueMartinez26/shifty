import { render, screen } from '@testing-library/react'

import type { BookingConfirmation } from '@application/services/PublicBookingService'

import { formatCurrency } from '@shared/utils/currency'

import { BookingSuccess } from './BookingSuccess'
import type { BookingWizardState } from './types'

// Varios servicios en un turno (2026-10-16): la pantalla de exito dice que se
// reservo con la etiqueta del backend ("Corte + Barba").

const estado: BookingWizardState = {
  serviceId: 'corte',
  extraServiceIds: ['barba'],
  requestedStaffId: null,
  assignedStaffId: 'st-1',
  assignedStaff: { name: 'Pro', isResource: false },
  date: '2026-09-25',
  startTime: '09:00',
  startsAt: '2026-09-25T12:00:00+00:00',
  client: {
    name: 'Lucia',
    email: 'lucia@example.com',
    phone: '1155550101',
    notes: '',
    customFields: {}
  },
  promotionCode: '',
  promotionPreview: null,
  addons: []
}

const confirmacion = (patch: Partial<BookingConfirmation> = {}): BookingConfirmation => ({
  public_id: 'apt-1',
  service_id: 'corte',
  service_name: 'Corte',
  staff_id: 'st-1',
  staff_name: 'Pro',
  starts_at: '2026-09-25T12:00:00+00:00',
  ends_at: '2026-09-25T12:45:00+00:00',
  status: 'confirmed',
  client_name: 'Lucia',
  client_phone: '1155550101',
  payment_required: false,
  ...patch
})

const renderExito = (confirmation: BookingConfirmation) =>
  render(
    <BookingSuccess
      confirmation={confirmation}
      bookingState={estado}
      storeSlug="tienda"
      storeName="Tienda"
      whatsappNumber={null}
    />
  )

describe('BookingSuccess: servicios del turno', () => {
  it('con varios servicios muestra la etiqueta del backend', () => {
    renderExito(
      confirmacion({
        extra_services: [{ public_id: 'barba', name: 'Barba', duration_minutes: 15 }],
        services_label: 'Corte + Barba'
      })
    )

    expect(screen.getByText('Servicios')).toBeInTheDocument()
    expect(screen.getByText('Corte + Barba')).toBeInTheDocument()
  })

  it('una respuesta sin etiqueta muestra el servicio principal', () => {
    renderExito(confirmacion())

    expect(screen.getByText('Servicio')).toBeInTheDocument()
    expect(screen.getByText('Corte')).toBeInTheDocument()
  })

  // Revision de #194 (M3): service_price es solo el principal; las lineas del
  // resumen tienen que sumar el total.
  describe('resumen comercial con varios servicios', () => {
    const resumen = () => screen.getByText('Resumen comercial').parentElement as HTMLElement
    const base = {
      service_price: 10000,
      final_price: 16000,
      addons: [{ addon_id: 'toalla', name: 'Toalla', unit_price: 500, quantity: 2, amount: 1000 }],
      services_label: 'Corte + Barba'
    }

    it('con el precio de cada servicio va una linea por servicio', () => {
      renderExito(
        confirmacion({
          ...base,
          extra_services: [{ public_id: 'barba', name: 'Barba', duration_minutes: 15, price: 5000 }]
        })
      )

      expect(resumen()).toHaveTextContent(
        `Corte: ${formatCurrency(10000)}Barba: ${formatCurrency(5000)}Toalla x2: ${formatCurrency(1000)}Total final: ${formatCurrency(16000)}`
      )
    })

    it('sin el precio de cada uno pero con extra_services_amount va una sola linea con la suma', () => {
      renderExito(
        confirmacion({
          ...base,
          extra_services: [{ public_id: 'barba', name: 'Barba', duration_minutes: 15 }],
          extra_services_amount: 5000
        })
      )

      expect(resumen()).toHaveTextContent(
        `Servicios (Corte + Barba): ${formatCurrency(15000)}Toalla x2`
      )
    })

    it('sin ninguno de los dos no muestra un importe que no cierra: solo el total', () => {
      renderExito(
        confirmacion({
          ...base,
          extra_services: [{ public_id: 'barba', name: 'Barba', duration_minutes: 15 }]
        })
      )

      expect(resumen()).not.toHaveTextContent(`Servicio: ${formatCurrency(10000)}`)
      expect(resumen()).toHaveTextContent(`Total final: ${formatCurrency(16000)}`)
    })

    it('con un solo servicio sigue diciendo "Servicio"', () => {
      renderExito(confirmacion({ service_price: 10000, final_price: 10000 }))

      expect(resumen()).toHaveTextContent(`Servicio: ${formatCurrency(10000)}`)
    })
  })
})
