import type { ReactElement } from 'react'

import { fireEvent, render as rtlRender, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'

import { Staff } from '@domain/entities/Staff'

import { createStaffSchema } from '@application/validators/staff.validators'

import { ValidationError } from '@shared/errors'

import { StaffFormModal } from './StaffFormModal'

const SERVICIO = { id: 'svc-1', name: 'Corte', duration: { getValue: () => 30 } }
let mockServices: unknown[] | undefined = [SERVICIO]

jest.mock('@presentation/hooks/useManagedServices', () => ({
  useManagedServices: () => ({ data: mockServices })
}))

// El aviso de "sin servicios" lleva un <Link> al panel de Servicios.
const render = (ui: ReactElement) => rtlRender(<MemoryRouter>{ui}</MemoryRouter>)

beforeEach(() => {
  mockServices = [SERVICIO]
})

const montar = (readOnlyReason?: string | null) =>
  render(
    <StaffFormModal
      isOpen
      onClose={jest.fn()}
      onSubmit={jest.fn().mockResolvedValue(undefined)}
      readOnlyReason={readOnlyReason}
    />
  )

describe('StaffFormModal: tienda suspendida', () => {
  // 2026-10-02: si la tienda se suspendia con el modal abierto, guardar
  // fallaba con 402 en vez de verse deshabilitado (FF-15). POST y PUT
  // /staff/... no estan en SUSPENSION_ALLOWED_WRITES.
  it('con la tienda suspendida guardar queda deshabilitado con el motivo', () => {
    montar('Tienda suspendida')

    const guardar = screen.getByRole('button', { name: 'Dar de Alta Profesional' })
    expect(guardar).toBeDisabled()
    expect(guardar).toHaveAttribute('title', 'Tienda suspendida')
  })

  it('sin suspension guardar sigue habilitado y sin motivo', () => {
    montar()

    const guardar = screen.getByRole('button', { name: 'Dar de Alta Profesional' })
    expect(guardar).not.toBeDisabled()
    expect(guardar).not.toHaveAttribute('title')
  })
})

// 2026-10-08, decision de Mateo: el dueno se agrega como profesional con su
// cuenta. Nombre, apellido y email salen de la cuenta: no se piden.
describe('StaffFormModal: agregarme como profesional', () => {
  it('no pide nombre, apellido ni email y propone el nombre de la cuenta', async () => {
    const onSubmit = jest.fn().mockResolvedValue(undefined)
    render(
      <StaffFormModal
        isOpen
        onClose={jest.fn()}
        onSubmit={onSubmit}
        selfName="Enrique Martinez"
        selfEmail="duenio@example.com"
      />
    )

    expect(screen.getByText('Agregarme como profesional')).toBeInTheDocument()
    expect(screen.getByText(/no se crea otro usuario ni otra clave/i)).toHaveTextContent(
      'duenio@example.com'
    )
    expect(screen.queryByPlaceholderText('Ej: Marcelo')).not.toBeInTheDocument()
    expect(screen.queryByPlaceholderText('marcelo@shifty.com')).not.toBeInTheDocument()
    expect(screen.queryByRole('radiogroup', { name: 'Tipo' })).not.toBeInTheDocument()
    expect((screen.getByPlaceholderText('Ej: Marce R.') as HTMLInputElement).value).toBe(
      'Enrique Martinez'
    )

    fireEvent.click(screen.getByRole('button', { name: 'Agregarme' }))

    await waitFor(() =>
      expect(onSubmit).toHaveBeenCalledWith(
        expect.objectContaining({ display_name: 'Enrique Martinez', service_ids: [] })
      )
    )
  })

  it('editando la ficha propia el email de login no se cambia', () => {
    const propia = Staff.fromPrimitives({
      public_id: 'usr-duenio',
      kind: 'person',
      first_name: 'Enrique',
      last_name: 'Martinez',
      email: 'duenio@example.com',
      display_name: 'Enrique',
      is_active: true,
      service_ids: []
    })
    render(
      <StaffFormModal
        isOpen
        onClose={jest.fn()}
        onSubmit={jest.fn()}
        editingStaff={propia}
        isOwnAccount
      />
    )

    const email = screen.getByPlaceholderText('marcelo@shifty.com')
    expect(email).toHaveAttribute('readonly')
    const hint = document.getElementById(email.getAttribute('aria-describedby') ?? '')
    expect(hint).toHaveTextContent('Es el email con el que entrás: acá no se cambia.')
  })
})

// 2026-10-14, produccion (primera tienda real): sin servicios cargados el alta
// de un profesional fallaba con "No se pudo guardar" y la lista de
// especialidades vacia no decia que hacer.
describe('StaffFormModal: tienda sin servicios', () => {
  const AVISO =
    'Primero creá al menos un servicio en Servicios: cada profesional tiene que tener uno asignado.'

  it('avisa, enlaza a Servicios y deshabilita guardar con el motivo', () => {
    mockServices = []
    montar()

    expect(screen.getByText(AVISO)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Ir a Servicios' })).toHaveAttribute(
      'href',
      '/dashboard/services'
    )
    const guardar = screen.getByRole('button', { name: 'Dar de Alta Profesional' })
    expect(guardar).toBeDisabled()
    expect(guardar).toHaveAttribute('title', AVISO)
  })

  it('mientras el catalogo carga no avisa ni bloquea', () => {
    mockServices = undefined
    montar()

    expect(screen.queryByText(AVISO)).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Dar de Alta Profesional' })).not.toBeDisabled()
  })

  it('con servicios no hay aviso y se elige entre ellos', () => {
    montar()

    expect(screen.queryByText(AVISO)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Ir a Servicios' })).not.toBeInTheDocument()
    expect(screen.getByText('Corte')).toBeInTheDocument()
  })

  it('"Agregarme como profesional" muestra el mismo aviso y no deja guardar', () => {
    mockServices = []
    render(
      <StaffFormModal
        isOpen
        onClose={jest.fn()}
        onSubmit={jest.fn()}
        selfName="Enrique Martinez"
        selfEmail="duenio@example.com"
      />
    )

    expect(screen.getByText(AVISO)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Ir a Servicios' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Agregarme' })).toBeDisabled()
  })
})

describe('StaffFormModal: errores por campo', () => {
  const guardarConError = async (error: unknown) => {
    render(
      <StaffFormModal
        isOpen
        onClose={jest.fn()}
        onSubmit={jest.fn().mockRejectedValue(error)}
        selfName="Enrique Martinez"
      />
    )
    fireEvent.click(screen.getByRole('button', { name: 'Agregarme' }))
    return await screen.findByRole('alert')
  }

  it('la validacion del cliente sobre service_ids dice que falta un servicio', async () => {
    const zod = createStaffSchema.safeParse({ display_name: 'Enrique', service_ids: [] })
    if (zod.success) throw new Error('el esquema deberia rechazar service_ids vacio')
    // BaseService.handleError deja el ZodError en originalError de un Error plano.
    const envuelto = Object.assign(new Error('Error de validación'), { originalError: zod.error })

    const alerta = await guardarConError(envuelto)

    expect(alerta).toHaveTextContent('Debe tener al menos un servicio asignado')
    expect(alerta).not.toHaveTextContent('No se pudo guardar')
  })

  it('un 422 del servidor en service_ids dice que elegir, sin texto crudo', async () => {
    const alerta = await guardarConError(
      new ValidationError('body -> service_ids: List should have at least 1 item', {
        errorCode: 'VALIDATION_ERROR',
        statusCode: 422,
        detail: ['service_ids: List should have at least 1 item']
      })
    )

    expect(alerta).toHaveTextContent('Elegí al menos un servicio')
    expect(alerta).not.toHaveTextContent('List should')
  })
})
