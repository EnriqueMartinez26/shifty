import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import PromotionsPage from './Promotions'
import type { PromotionPayload, PromotionRecord } from '../../application/services/PaymentsService'

const mockCreateMutateAsync = jest.fn()
const mockUpdateMutateAsync = jest.fn()
let mockPromotions: PromotionRecord[] = []

jest.mock('../hooks/usePayments', () => ({
  usePromotions: () => ({ data: mockPromotions, isLoading: false, error: null }),
  useCreatePromotion: () => ({ mutateAsync: mockCreateMutateAsync, isPending: false }),
  useUpdatePromotion: () => ({ mutateAsync: mockUpdateMutateAsync, isPending: false })
}))

let mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
jest.mock('../hooks/useStoreWriteAccess', () => ({
  useStoreWriteAccess: () => mockWriteAccess
}))

const CAMPOS_OPCIONALES = [
  'description',
  'min_service_amount',
  'max_uses',
  'valid_from',
  'valid_until'
] as const

const buildPromotion = (overrides: Partial<PromotionRecord> = {}): PromotionRecord => ({
  public_id: 'promo-1',
  code: 'BIENVENIDA10',
  title: 'Descuento primera visita',
  description: 'Solo para clientes nuevos',
  promotion_type: 'percent',
  value: 10,
  min_service_amount: 1500,
  max_uses: 20,
  current_uses: 3,
  valid_from: '2026-10-01T03:00:00.000Z',
  valid_until: '2026-10-31T03:00:00.000Z',
  is_active: true,
  created_at: '2026-09-01T12:00:00.000Z',
  updated_at: '2026-09-01T12:00:00.000Z',
  ...overrides
})

// Lo que axios pone en el cuerpo: JSON.stringify descarta las claves undefined.
const enElCable = (payload: Partial<PromotionPayload>): Record<string, unknown> =>
  JSON.parse(JSON.stringify(payload)) as Record<string, unknown>

const inputsDeFecha = (container: HTMLElement) =>
  Array.from(container.querySelectorAll<HTMLInputElement>('input[type="datetime-local"]'))

const inputsOpcionales = () => screen.getAllByPlaceholderText('Opcional')

const valorDelContador = (label: string) =>
  screen.getByText(label).nextElementSibling?.textContent ?? null

describe('PromotionsPage', () => {
  beforeEach(() => {
    mockPromotions = []
    mockCreateMutateAsync.mockReset().mockResolvedValue(buildPromotion())
    mockUpdateMutateAsync.mockReset().mockResolvedValue(buildPromotion())
  })

  it('al editar, vaciar los cinco campos opcionales los manda en null', async () => {
    // 2026-09-30: vaciar un campo de una promocion no lo borraba: axios omite
    // undefined y el PATCH (exclude_unset) dejaba el valor viejo guardado.
    mockPromotions = [buildPromotion()]
    const { container } = render(<PromotionsPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Editar' }))
    fireEvent.change(screen.getByPlaceholderText('Texto interno para el equipo.'), {
      target: { value: '   ' }
    })
    const [minimo, usos] = inputsOpcionales()
    fireEvent.change(minimo!, { target: { value: '' } })
    fireEvent.change(usos!, { target: { value: '' } })
    const [desde, hasta] = inputsDeFecha(container)
    fireEvent.change(desde!, { target: { value: '' } })
    fireEvent.change(hasta!, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Actualizar' }))

    await waitFor(() => expect(mockUpdateMutateAsync).toHaveBeenCalledTimes(1))
    const { promotionId, payload } = mockUpdateMutateAsync.mock.calls[0][0] as {
      promotionId: string
      payload: Partial<PromotionPayload>
    }
    expect(promotionId).toBe('promo-1')
    const cuerpo = enElCable(payload)
    for (const campo of CAMPOS_OPCIONALES) {
      expect(cuerpo).toHaveProperty(campo, null)
    }
    // Los obligatorios nunca viajan en null: el setattr del backend los pisaria.
    expect(cuerpo).toMatchObject({
      code: 'BIENVENIDA10',
      title: 'Descuento primera visita',
      promotion_type: 'percent',
      value: 10
    })
  })

  it('al crear, los campos opcionales vacios no viajan', async () => {
    // 2026-09-30: vaciar un campo de una promocion no lo borraba: axios omite
    // undefined. En el alta se sigue omitiendo: el backend pone sus defaults.
    render(<PromotionsPage />)

    fireEvent.change(screen.getByPlaceholderText('BIENVENIDA10'), { target: { value: 'nueva5' } })
    fireEvent.change(screen.getByPlaceholderText('Descuento primera visita'), {
      target: { value: 'Promo nueva' }
    })
    fireEvent.change(screen.getByPlaceholderText('10'), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: 'Crear' }))

    await waitFor(() => expect(mockCreateMutateAsync).toHaveBeenCalledTimes(1))
    const cuerpo = enElCable(mockCreateMutateAsync.mock.calls[0][0] as PromotionPayload)
    for (const campo of CAMPOS_OPCIONALES) {
      expect(cuerpo).not.toHaveProperty(campo)
    }
    expect(cuerpo).toMatchObject({ code: 'NUEVA5', title: 'Promo nueva', value: 5 })
  })

  it('vaciar solo el vencimiento conserva el inicio de la vigencia', async () => {
    // 2026-09-30: vaciar un campo de una promocion no lo borraba: axios omite
    // undefined. Borrar "Hasta" no puede arrastrar a "Desde".
    mockPromotions = [buildPromotion()]
    const { container } = render(<PromotionsPage />)

    fireEvent.click(screen.getByRole('button', { name: 'Editar' }))
    const [, hasta] = inputsDeFecha(container)
    fireEvent.change(hasta!, { target: { value: '' } })
    fireEvent.click(screen.getByRole('button', { name: 'Actualizar' }))

    await waitFor(() => expect(mockUpdateMutateAsync).toHaveBeenCalledTimes(1))
    const { payload } = mockUpdateMutateAsync.mock.calls[0][0] as {
      payload: Partial<PromotionPayload>
    }
    const cuerpo = enElCable(payload)
    expect(cuerpo).toHaveProperty('valid_until', null)
    expect(cuerpo).toHaveProperty('valid_from', '2026-10-01T03:00:00.000Z')
    expect(cuerpo).toMatchObject({
      description: 'Solo para clientes nuevos',
      min_service_amount: 1500,
      max_uses: 20
    })
  })

  it('los contadores de activas, totales y con limite salen de la lista', () => {
    // Cubre el calculo inline que reemplazo al useMemo (F11b-16).
    mockPromotions = [
      buildPromotion({ public_id: 'promo-1' }),
      buildPromotion({ public_id: 'promo-2', code: 'OTRA', max_uses: null }),
      buildPromotion({ public_id: 'promo-3', code: 'VIEJA', is_active: false, max_uses: null })
    ]
    render(<PromotionsPage />)

    expect(valorDelContador('Activas')).toBe('2')
    expect(valorDelContador('Totales')).toBe('3')
    expect(valorDelContador('Con límite')).toBe('1')
  })
})

// 2026-10-01: con la tienda suspendida cada accion fallaba con 402 en vez de
// verse deshabilitada (FF-15). POST /promotions/ y PATCH /promotions/{id} no
// estan en SUSPENSION_ALLOWED_WRITES.
describe('PromotionsPage: tienda suspendida', () => {
  beforeEach(() => {
    mockPromotions = [buildPromotion()]
    mockUpdateMutateAsync.mockReset()
  })

  afterEach(() => {
    mockWriteAccess = { readOnly: false, reason: 'Tienda suspendida' }
  })

  it('con la tienda suspendida crear, actualizar y pausar quedan deshabilitados', () => {
    mockWriteAccess = { readOnly: true, reason: 'Tienda suspendida' }
    render(<PromotionsPage />)

    for (const name of ['Crear', 'Pausar']) {
      const button = screen.getByRole('button', { name })
      expect(button).toBeDisabled()
      expect(button).toHaveAttribute('title', 'Tienda suspendida')
    }
    // Editar solo carga el formulario; lo que escribe es "Actualizar".
    fireEvent.click(screen.getByRole('button', { name: 'Editar' }))
    expect(screen.getByRole('button', { name: 'Actualizar' })).toBeDisabled()
    fireEvent.click(screen.getByRole('button', { name: 'Pausar' }))
    expect(mockUpdateMutateAsync).not.toHaveBeenCalled()
  })

  it('con la tienda suspendida una pausada no se puede reactivar', () => {
    mockWriteAccess = { readOnly: true, reason: 'Tienda suspendida' }
    mockPromotions = [buildPromotion({ is_active: false })]
    render(<PromotionsPage />)

    expect(screen.getByRole('button', { name: 'Reactivar' })).toBeDisabled()
  })

  it('sin suspension crear y pausar siguen habilitados', () => {
    render(<PromotionsPage />)

    expect(screen.getByRole('button', { name: 'Crear' })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: 'Pausar' })).not.toBeDisabled()
  })
})
