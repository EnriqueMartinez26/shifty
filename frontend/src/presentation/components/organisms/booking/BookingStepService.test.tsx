import { render, screen } from '@testing-library/react'

import { BookingStepService } from './BookingStepService'

// 2026-10-02 (F4-15): las fotos del primer paso de la reserva no tenian tamano
// ni carga diferida: el celular bajaba todas y la lista saltaba al llegar cada
// una.

const mockUsePublicServices = jest.fn()

jest.mock('@presentation/hooks/usePublic', () => ({
  usePublicServices: (...args: unknown[]) => mockUsePublicServices(...args)
}))

describe('BookingStepService', () => {
  it('la foto del servicio reserva su caja de 56 px y carga diferida', () => {
    mockUsePublicServices.mockReturnValue({
      isLoading: false,
      data: [
        {
          public_id: 'svc-1',
          name: 'Corte',
          description: null,
          duration_minutes: 30,
          price: 10000,
          color: '#3b82f6',
          image_url: 'https://cdn.test/corte.png'
        }
      ]
    })

    render(<BookingStepService storePublicId="store-1" selectedId={null} onSelect={jest.fn()} />)

    const img = screen.getByRole('img', { name: 'Corte' })
    expect(img).toHaveAttribute('loading', 'lazy')
    expect(img).toHaveAttribute('decoding', 'async')
    expect(img).toHaveAttribute('width', '56')
    expect(img).toHaveAttribute('height', '56')
  })

  // QA movil 2026-10-08 (QA!): en 390 px el nombre salia cortado ("BARBA Y
  // PERFILAD"), el precio recortado y el circulo de seleccion encima del titulo.
  it('en una tarjeta angosta el nombre corta en lineas y nada se superpone', () => {
    mockUsePublicServices.mockReturnValue({
      isLoading: false,
      data: [
        {
          public_id: 'svc-2',
          name: 'Barba y perfilado',
          description: null,
          duration_minutes: 20,
          price: 900,
          color: null,
          image_url: null
        }
      ]
    })

    render(<BookingStepService storePublicId="store-1" selectedId={null} onSelect={jest.fn()} />)

    const name = screen.getByText('Barba y perfilado')
    expect(name.classList.contains('break-words')).toBe(true)
    const badges = name.nextElementSibling
    expect(badges?.classList.contains('flex-wrap')).toBe(true)
    const check = screen.getByRole('button').lastElementChild
    expect(check?.classList.contains('flex-shrink-0')).toBe(true)
  })
})
