import { fireEvent, render, screen } from '@testing-library/react'

import { AddonSelection } from '@domain/value-objects/AddonSelection'

import { publicAddonOptions } from '@application/mappers/PublicAddonMapper'
import type { PublicService } from '@application/services/PublicBookingService'

import { formatCurrency } from '@shared/utils/currency'

import type { ServiceAddonsGroup } from './addonGroups'
import { BookingStepService } from './BookingStepService'
import { colors2000s } from '../../../../theme/colors'

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

  it('muestra la selección naranja con texto blanco de contraste AA', () => {
    mockUsePublicServices.mockReturnValue({
      isLoading: false,
      data: [servicio('corte', 'Corte', 30, 10000)]
    })

    render(<BookingStepService storePublicId="store-1" selectedId="corte" onSelect={jest.fn()} />)

    // Con el color de la tienda (S3) la seleccion lee var(--brand-*); sin
    // color de tienda el respaldo de cada var() es la rampa de #240.
    const title = screen.getByText('Corte')
    expect(title.style.color).toBe(`var(--brand-on-fill, ${colors2000s.text.onOrangeSelection})`)
    expect(colors2000s.text.onOrangeSelection).toBe('#ffffff')
    const fondo = title.closest('button')?.style.background ?? ''
    expect(fondo).toContain(`var(--brand-fill, ${colors2000s.orange.cta})`)
    expect(fondo).toContain(`var(--brand-fill-bottom, ${colors2000s.orange.ctaEnd})`)
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

  // QA 2026-10-21: con un color de tienda claro (amarillo) el icono pintado
  // con el relleno quedaba en 1.07:1 sobre el blanco de la tarjeta.
  it.each([
    ['sin color propio', null],
    ['con color propio', '#ffff00']
  ])('el icono del servicio %s es neutro, legible sobre claro (S9)', (_caso, color) => {
    mockUsePublicServices.mockReturnValue({
      isLoading: false,
      data: [{ ...servicio('corte', 'Corte', 30, 10000), color }]
    })

    render(<BookingStepService storePublicId="store-1" selectedId={null} onSelect={jest.fn()} />)

    const avatar = screen.getByRole('button').querySelector('svg.lucide-briefcase')?.parentElement
    expect(avatar?.getAttribute('style')).not.toContain('--brand')
    expect(avatar?.style.color).toBe('rgb(64, 64, 64)')
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

// S4 (2026-10-21): tocar un servicio lo elige y abre, debajo, el contador de
// sus adicionales; la barra suma el total al momento.
describe('BookingStepService con adicionales', () => {
  const conAdicionales = (
    public_id: string,
    name: string,
    price: number,
    addons: { id: string; name: string; unit_price: number; max_quantity: number }[]
  ) => ({
    ...servicio(public_id, name, 30, price),
    addons: addons.map((addon, position) => ({ ...addon, position }))
  })
  const catalogo = [
    conAdicionales('corte', 'Corte', 10000, [
      { id: 'strass', name: 'Strass', unit_price: 500, max_quantity: 10 }
    ]),
    conAdicionales('barba', 'Barba', 5000, [
      { id: 'brillo', name: 'Brillo', unit_price: 1500, max_quantity: 2 }
    ]),
    servicio('lavado', 'Lavado', 10, 2000)
  ]
  // Lo que arma el contenedor con groupAddonsByService.
  const grupos = (
    elegidos: string[],
    cantidades: Record<string, Record<string, number>> = {}
  ): ServiceAddonsGroup[] =>
    elegidos.map((id) => {
      const service = catalogo.find((svc) => svc.public_id === id) as unknown as PublicService
      const options = publicAddonOptions(service)
      return {
        serviceId: id,
        service,
        options,
        selection: AddonSelection.create(options, cantidades[id] ?? {}),
        changed: false,
        hasChosen: false
      }
    })

  const renderUno = (
    selectedId: string | null,
    cantidades: Record<string, Record<string, number>> = {}
  ) => {
    mockUsePublicServices.mockReturnValue({ isLoading: false, data: catalogo })
    const onChange = jest.fn()
    const onContinue = jest.fn()
    const onSelect = jest.fn()
    render(
      <BookingStepService
        storePublicId="store-1"
        selectedId={selectedId}
        onSelect={onSelect}
        addons={{
          groups: grupos(selectedId ? [selectedId] : [], cantidades),
          onChange,
          onContinue
        }}
      />
    )
    return { onChange, onContinue, onSelect }
  }

  const tarjeta = (name: string) => screen.getByRole('button', { name: new RegExp(name) })

  it('el servicio elegido abre sus adicionales debajo, asociados a su tarjeta', () => {
    renderUno('corte')

    const region = screen.getByRole('region', { name: 'Adicionales de Corte' })
    expect(tarjeta('Corte')).toHaveAttribute('aria-expanded', 'true')
    expect(tarjeta('Corte')).toHaveAttribute('aria-controls', region.id)
    expect(tarjeta('Corte').nextElementSibling).toBe(region)
    expect(screen.getByLabelText('Cantidad de Strass')).toHaveTextContent('0')
    // Lo que no esta elegido no se abre.
    expect(tarjeta('Barba')).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('region', { name: 'Adicionales de Barba' })).not.toBeInTheDocument()
    // Un servicio sin adicionales no tiene nada que abrir.
    expect(tarjeta('Lavado')).not.toHaveAttribute('aria-expanded')
  })

  it('el contador avisa el servicio, el adicional y la cantidad', () => {
    const { onChange } = renderUno('corte', { corte: { strass: 2 } })

    fireEvent.click(screen.getByRole('button', { name: 'Agregar uno de Strass' }))
    expect(onChange).toHaveBeenLastCalledWith('corte', 'strass', 3)
    fireEvent.click(screen.getByRole('button', { name: 'Quitar uno de Strass' }))
    expect(onChange).toHaveBeenLastCalledWith('corte', 'strass', 1)
  })

  it('con un servicio con adicionales elegido la barra suma el total y Continuar sigue', () => {
    const { onContinue } = renderUno('corte', { corte: { strass: 3 } })

    expect(screen.getByTestId('booking-services-bar')).toHaveTextContent(
      `1 servicio · 30 min · ${formatCurrency(11500)}`
    )
    fireEvent.click(screen.getByRole('button', { name: /Continuar/ }))
    expect(onContinue).toHaveBeenCalledTimes(1)
  })

  it('sin un servicio con adicionales elegido no hay barra ni contador', () => {
    renderUno(null)

    expect(screen.queryByTestId('booking-services-bar')).not.toBeInTheDocument()
    expect(screen.queryByRole('region')).not.toBeInTheDocument()
  })

  it('con varios servicios cada elegido abre los suyos y la barra suma todo', () => {
    mockUsePublicServices.mockReturnValue({ isLoading: false, data: catalogo })
    const onChange = jest.fn()
    render(
      <BookingStepService
        storePublicId="store-1"
        selectedId="corte"
        onSelect={jest.fn()}
        multiService={{
          selectedIds: ['corte', 'barba'],
          onToggle: jest.fn(),
          onContinue: jest.fn()
        }}
        addons={{
          groups: grupos(['corte', 'barba'], { corte: { strass: 1 }, barba: { brillo: 2 } }),
          onChange,
          onContinue: jest.fn()
        }}
      />
    )

    const deBarba = screen.getByRole('region', { name: 'Adicionales de Barba' })
    expect(tarjeta('Barba').nextElementSibling).toBe(deBarba)
    expect(screen.getByRole('region', { name: 'Adicionales de Corte' })).toBeInTheDocument()
    // 10000 + 5000 + 500 + 2 x 1500
    expect(screen.getByTestId('booking-services-bar')).toHaveTextContent(
      `2 servicios · 60 min · ${formatCurrency(18500)}`
    )
    fireEvent.click(screen.getByRole('button', { name: 'Quitar uno de Brillo' }))
    expect(onChange).toHaveBeenLastCalledWith('barba', 'brillo', 1)
  })
})

// S3 (2026-10-21): el servicio elegido se pinta con el color de la tienda
// (var(--brand-*), fijadas en la raiz del wizard), no con el naranja fijo.
describe('BookingStepService con el color de la tienda', () => {
  it('el servicio elegido usa el relleno de marca, su borde y el texto sobre el relleno', () => {
    mockUsePublicServices.mockReturnValue({
      isLoading: false,
      data: [servicio('svc-1', 'Corte', 30, 1000), servicio('svc-2', 'Barba', 20, 900)]
    })

    render(<BookingStepService storePublicId="store-1" selectedId="svc-1" onSelect={jest.fn()} />)

    const elegido = screen.getByRole('button', { name: /Corte/ })
    expect(elegido.getAttribute('style')).toContain('var(--brand-fill,')
    expect(elegido.getAttribute('style')).toContain('var(--brand-fill-bottom,')
    expect(elegido.getAttribute('style')).not.toContain('--brand-ink')
    expect(screen.getByText('Corte').getAttribute('style')).toContain('var(--brand-on-fill,')
    const otro = screen.getByRole('button', { name: /Barba/ })
    expect(otro.getAttribute('style')).not.toContain('var(--brand-fill,')
  })

  // QA visual 2026-10-21: la tarjeta elegida era la ultima con el brillo
  // naranja fijo debajo del color de la tienda.
  it('el servicio elegido brilla con el color de la tienda, no con el naranja fijo', () => {
    mockUsePublicServices.mockReturnValue({
      isLoading: false,
      data: [servicio('svc-1', 'Corte', 30, 1000)]
    })

    render(<BookingStepService storePublicId="store-1" selectedId="svc-1" onSelect={jest.fn()} />)

    const style = screen.getByRole('button', { name: /Corte/ }).getAttribute('style') ?? ''
    // El naranja solo queda como respaldo dentro del var(), sin color de tienda.
    expect(style).toContain('var(--brand-glow,')
  })
})
