import { render, screen } from '@testing-library/react'

import type { BookingConfirmation } from '@application/services/PublicBookingService'

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
})
