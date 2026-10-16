import { fireEvent, render, screen } from '@testing-library/react'

import { formatCurrency } from '@shared/utils/currency'

import { BookingStepService } from './BookingStepService'

// 2026-10-02 (F4-15): las fotos del primer paso de la reserva no tenian tamano
// ni carga diferida: el celular bajaba todas y la lista saltaba al llegar cada
// una.

const mockUsePublicServices = jest.fn()
const mockUsePublicStaff = jest.fn()

jest.mock('@presentation/hooks/usePublic', () => ({
  usePublicServices: (...args: unknown[]) => mockUsePublicServices(...args),
  usePublicStaff: (...args: unknown[]) => mockUsePublicStaff(...args)
}))

const servicio = (public_id: string, name: string, duration_minutes: number, price: number) => ({
  public_id,
  name,
  description: null,
  duration_minutes,
  price,
  deposit_mode: 'none',
  deposit_type: 'percent',
  deposit_amount: null,
  color: null,
  image_url: null
})

describe('BookingStepService', () => {
  beforeEach(() => {
    mockUsePublicServices.mockReset()
    mockUsePublicStaff.mockReset()
    mockUsePublicStaff.mockReturnValue({ data: undefined })
  })

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

  it('sin varios servicios tocar uno lo elige, no pide profesionales ni muestra la barra', () => {
    mockUsePublicServices.mockReturnValue({
      isLoading: false,
      data: [servicio('corte', 'Corte', 30, 10000), servicio('barba', 'Barba', 15, 5000)]
    })
    const onSelect = jest.fn()

    render(<BookingStepService storePublicId="store-1" selectedId={null} onSelect={onSelect} />)
    fireEvent.click(screen.getByText('Barba'))

    expect(onSelect).toHaveBeenCalledWith('barba')
    expect(mockUsePublicStaff).toHaveBeenCalledWith('store-1', undefined, false)
    expect(screen.queryByTestId('booking-services-bar')).not.toBeInTheDocument()
  })

  // Varios servicios en un turno (2026-10-16).
  describe('con varios servicios', () => {
    const catalogo = [
      servicio('corte', 'Corte', 30, 10000),
      servicio('barba', 'Barba', 15, 5000),
      servicio('color', 'Color', 120, 30000),
      servicio('lavado', 'Lavado', 10, 2000),
      servicio('alisado', 'Alisado', 400, 80000)
    ]
    const todos = { service_ids: catalogo.map((svc) => svc.public_id) }

    const renderMulti = (selectedIds: string[], staff: unknown = [todos]) => {
      mockUsePublicServices.mockReturnValue({ isLoading: false, data: catalogo })
      mockUsePublicStaff.mockReturnValue({ data: staff })
      const onToggle = jest.fn()
      const onContinue = jest.fn()
      const onSelect = jest.fn()
      render(
        <BookingStepService
          storePublicId="store-1"
          selectedId={selectedIds[0] ?? null}
          onSelect={onSelect}
          multiService={{ selectedIds, onToggle, onContinue }}
        />
      )
      return { onToggle, onContinue, onSelect }
    }

    const tarjeta = (name: string) => screen.getByRole('button', { name: new RegExp(name) })

    it('tocar un servicio lo suma o lo quita, sin avanzar', () => {
      const { onToggle, onSelect } = renderMulti(['corte'])

      expect(mockUsePublicStaff).toHaveBeenCalledWith('store-1', undefined, true)
      expect(tarjeta('Corte')).toHaveAttribute('aria-pressed', 'true')
      fireEvent.click(tarjeta('Barba'))
      fireEvent.click(tarjeta('Corte'))

      expect(onToggle).toHaveBeenNthCalledWith(1, 'barba')
      expect(onToggle).toHaveBeenNthCalledWith(2, 'corte')
      expect(onSelect).not.toHaveBeenCalled()
    })

    it('la barra dice cuantos, cuanto dura y cuanto suman, y Continuar avanza', () => {
      const { onContinue } = renderMulti(['corte', 'barba'])

      expect(screen.getByTestId('booking-services-bar')).toHaveTextContent(
        `2 servicios · 45 min · ${formatCurrency(15000)}`
      )
      fireEvent.click(screen.getByRole('button', { name: /Continuar/ }))
      expect(onContinue).toHaveBeenCalled()
    })

    it('sin nada elegido no hay barra', () => {
      renderMulti([])
      expect(screen.queryByTestId('booking-services-bar')).not.toBeInTheDocument()
    })

    it('con 3 elegidos los demas se apagan con el motivo; los elegidos se pueden quitar', () => {
      renderMulti(['corte', 'barba', 'lavado'])

      expect(tarjeta('Color')).toBeDisabled()
      expect(screen.getAllByText('Podés sumar hasta 3 servicios por turno.')).toHaveLength(2)
      expect(tarjeta('Lavado')).not.toBeDisabled()
    })

    it('lo que pasa de 8 horas se apaga: ya no entra en un turno', () => {
      renderMulti(['color'])

      expect(tarjeta('Alisado')).toBeDisabled()
      expect(screen.getByText('Ya no entra en un turno.')).toBeInTheDocument()
      expect(tarjeta('Corte')).not.toBeDisabled()
    })

    it('lo que ningun profesional hace junto con lo elegido se apaga', () => {
      renderMulti(['corte'], [{ service_ids: ['corte', 'barba'] }, { service_ids: ['color'] }])

      expect(tarjeta('Barba')).not.toBeDisabled()
      expect(tarjeta('Color')).toBeDisabled()
      expect(
        screen.getAllByText('Ningún profesional lo hace junto con lo que elegiste.').length
      ).toBeGreaterThan(0)
    })
  })
})
