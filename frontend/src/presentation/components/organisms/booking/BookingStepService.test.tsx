import { fireEvent, render, screen } from '@testing-library/react'

import { formatCurrency } from '@shared/utils/currency'

import { BookingStepService } from './BookingStepService'
import { colors2000s } from '../../../../theme/colors'
import { contrastRatio, DEFAULT_BRAND_THEME } from '../../../lib/brandTheme'

// 2026-10-02 (F4-15): las fotos del primer paso de la reserva no tenian tamano
// ni carga diferida: el celular bajaba todas y la lista saltaba al llegar cada
// una.

const mockUsePublicServices = jest.fn()

// Sin usePublicStaff: quien hace que lo trae el contenedor por props
// (revision de #194, CLAUDE.md §2).
jest.mock('@presentation/hooks/usePublic', () => ({
  usePublicServices: (...args: unknown[]) => mockUsePublicServices(...args)
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

  it('muestra la selección con el naranja del logo y texto de contraste AA', () => {
    mockUsePublicServices.mockReturnValue({
      isLoading: false,
      data: [servicio('corte', 'Corte', 30, 10000)]
    })

    render(<BookingStepService storePublicId="store-1" selectedId="corte" onSelect={jest.fn()} />)

    // Con el color de la tienda (S3) la seleccion lee var(--brand-*); sin
    // color de tienda el respaldo es el naranja del logo con texto oscuro
    // (revision de Enrique en #239: el blanco no llega a AA sobre ese naranja).
    const title = screen.getByText('Corte')
    expect(title.style.color).toBe(`var(--brand-on-fill, ${DEFAULT_BRAND_THEME.onFill})`)
    expect(
      contrastRatio(DEFAULT_BRAND_THEME.onFill, DEFAULT_BRAND_THEME.fill)
    ).toBeGreaterThanOrEqual(4.5)
    const fondo = title.closest('button')?.style.background ?? ''
    expect(fondo).toContain(`var(--brand-fill, ${colors2000s.orange.light})`)
    expect(fondo).toContain(`var(--brand-fill-bottom, ${colors2000s.orange.dark})`)
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

  it('sin varios servicios tocar uno lo elige y no muestra la barra', () => {
    mockUsePublicServices.mockReturnValue({
      isLoading: false,
      data: [servicio('corte', 'Corte', 30, 10000), servicio('barba', 'Barba', 15, 5000)]
    })
    const onSelect = jest.fn()

    render(<BookingStepService storePublicId="store-1" selectedId={null} onSelect={onSelect} />)
    fireEvent.click(screen.getByText('Barba'))

    expect(onSelect).toHaveBeenCalledWith('barba')
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
    const todos = { serviceIds: catalogo.map((svc) => svc.public_id) }

    const renderMulti = (
      selectedIds: string[],
      // null: la lista todavia no llego.
      performers: { serviceIds: string[] }[] | null = [todos]
    ) => {
      mockUsePublicServices.mockReturnValue({ isLoading: false, data: catalogo })
      const onToggle = jest.fn()
      const onContinue = jest.fn()
      const onSelect = jest.fn()
      render(
        <BookingStepService
          storePublicId="store-1"
          selectedId={selectedIds[0] ?? null}
          onSelect={onSelect}
          multiService={{
            selectedIds,
            onToggle,
            onContinue,
            performers: performers ?? undefined
          }}
        />
      )
      return { onToggle, onContinue, onSelect }
    }

    const tarjeta = (name: string) => screen.getByRole('button', { name: new RegExp(name) })

    it('tocar un servicio lo suma o lo quita, sin avanzar', () => {
      const { onToggle, onSelect } = renderMulti(['corte'])

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
      renderMulti(['corte'], [{ serviceIds: ['corte', 'barba'] }, { serviceIds: ['color'] }])

      expect(tarjeta('Barba')).not.toBeDisabled()
      expect(tarjeta('Color')).toBeDisabled()
      expect(
        screen.getAllByText('Ningún profesional lo hace junto con lo que elegiste.').length
      ).toBeGreaterThan(0)
    })

    it('sin la lista de profesionales (cargando) no apaga nada por profesional', () => {
      renderMulti(['corte'], null)

      expect(tarjeta('Color')).not.toBeDisabled()
      expect(
        screen.queryByText('Ningún profesional lo hace junto con lo que elegiste.')
      ).not.toBeInTheDocument()
    })
  })
})

// S3 (2026-10-21): el servicio elegido se pinta con el color de la tienda
// (var(--brand-*), fijadas en la raiz del wizard), no con el naranja fijo.
describe('BookingStepService con el color de la tienda', () => {
  it('el servicio elegido usa el relleno, el borde y el texto de marca', () => {
    mockUsePublicServices.mockReturnValue({
      isLoading: false,
      data: [servicio('svc-1', 'Corte', 30, 1000), servicio('svc-2', 'Barba', 20, 900)]
    })

    render(<BookingStepService storePublicId="store-1" selectedId="svc-1" onSelect={jest.fn()} />)

    const elegido = screen.getByRole('button', { name: /Corte/ })
    expect(elegido.getAttribute('style')).toContain('var(--brand-fill,')
    expect(elegido.getAttribute('style')).toContain('var(--brand-ink,')
    expect(screen.getByText('Corte').getAttribute('style')).toContain('var(--brand-on-fill,')
    const otro = screen.getByRole('button', { name: /Barba/ })
    expect(otro.getAttribute('style')).not.toContain('var(--brand-fill,')
  })
})
