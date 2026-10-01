import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

import { User } from '@domain/entities/User'

import { UserManagementContainer } from './UserManagementContainer'

const mockUpdate = jest.fn()
const mockCreate = jest.fn()
const mockDelete = jest.fn()
const mockListQuery = jest.fn()
let mockViewer: { public_id: string; is_global_admin?: boolean } = { public_id: 'admin-1' }
const mockFetchNextPage = jest.fn()
type UsersQuery = {
  data?: User[]
  isLoading: boolean
  error: unknown
  hasNextPage?: boolean
  isFetchingNextPage?: boolean
}
let mockUsersQuery: UsersQuery = { data: [], isLoading: false, error: null }

const usuario = User.fromPrimitives({
  id: 'usr-1',
  email: 'ana@example.com',
  firstName: 'Ana',
  lastName: 'Gomez',
  phone: '1155550101',
  role: 'receptionist',
  isActive: true,
  createdAt: '2026-09-01T12:00:00+00:00'
})

jest.mock('../hooks/useManagedDomainUsers', () => ({
  useManagedDomainUsers: (query: unknown) => {
    mockListQuery(query)
    return { fetchNextPage: mockFetchNextPage, ...mockUsersQuery }
  },
  useCreateManagedDomainUser: () => ({ mutateAsync: mockCreate }),
  useUpdateManagedDomainUser: () => ({ mutateAsync: mockUpdate }),
  useDeleteManagedDomainUser: () => ({ mutateAsync: mockDelete })
}))

jest.mock('../context/AuthContext', () => ({
  useAuth: () => ({ user: mockViewer })
}))

const otroAdmin = User.fromPrimitives({
  id: 'usr-2',
  email: 'beto@example.com',
  firstName: 'Beto',
  lastName: null,
  phone: null,
  role: 'admin',
  isActive: true,
  createdAt: '2026-09-01T12:00:00+00:00'
})

const opcionesDeRol = () =>
  Array.from(screen.getByRole('combobox').querySelectorAll('option')).map((o) => o.textContent)

describe('UserManagementContainer', () => {
  beforeEach(() => {
    mockUsersQuery = { data: [usuario], isLoading: false, error: null }
    mockViewer = { public_id: 'admin-1' }
    mockDelete.mockReset()
    mockUpdate.mockReset()
    mockUpdate.mockResolvedValue(usuario)
  })

  it('edita un usuario mandando solo lo que cambio, en UserWriteInput', async () => {
    // F11c-11: el submit hacia `formData as unknown as UpdateUserInput` y el
    // repositorio adivinaba snake_case o camelCase. FF-10: ahora ademas el
    // PATCH lleva solo lo cambiado; los campos intactos no viajan.
    render(<UserManagementContainer />)

    fireEvent.click(screen.getByRole('button', { name: /editar/i }))
    fireEvent.change(screen.getByDisplayValue('Ana'), { target: { value: '  Ana Maria ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Guardar Cambios' }))

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1))
    expect(mockUpdate).toHaveBeenCalledWith({ id: 'usr-1', data: { firstName: 'Ana Maria' } })
    expect(mockCreate).not.toHaveBeenCalled()
  })

  it('vaciar el telefono al editar lo borra con null, no con texto vacio (FF-10)', async () => {
    render(<UserManagementContainer />)

    fireEvent.click(screen.getByRole('button', { name: /editar/i }))
    fireEvent.change(screen.getByDisplayValue('1155550101'), { target: { value: '   ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Guardar Cambios' }))

    await waitFor(() => expect(mockUpdate).toHaveBeenCalledTimes(1))
    expect(mockUpdate).toHaveBeenCalledWith({ id: 'usr-1', data: { phone: null } })
  })

  it('crear con nombre en blanco no manda texto vacio (FF-10: era un 422)', async () => {
    mockCreate.mockReset()
    mockCreate.mockResolvedValue(usuario)
    const claveTipeada = 'claveSegura123'
    const { container } = render(<UserManagementContainer />)

    fireEvent.click(screen.getByRole('button', { name: /nuevo usuario/i }))
    const [email, nombre] = Array.from(
      container.querySelectorAll<HTMLInputElement>(
        'form:not([role="search"]) input:not([type="password"])'
      )
    )
    fireEvent.change(email!, { target: { value: 'luz@example.com' } })
    fireEvent.change(nombre!, { target: { value: '   ' } })
    fireEvent.change(container.querySelector('form input[type="password"]')!, {
      target: { value: claveTipeada }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Crear Usuario' }))

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    expect(mockCreate).toHaveBeenCalledWith({
      email: 'luz@example.com',
      password: claveTipeada,
      firstName: undefined,
      lastName: undefined,
      phone: undefined,
      role: 'staff'
    })
  })

  it('crea un usuario mandando CreateUserInput mapeado, no el formulario crudo', async () => {
    // El alta pasaba el formulario snake_case tal cual y UserService.createUser
    // lo recuperaba con `as unknown as Record`; ahora el borde lo verifica TS.
    mockCreate.mockReset()
    mockCreate.mockResolvedValue(usuario)
    // En una constante: `password: '<literal>'` dispara la regla generica de
    // gitleaks (secret-scan en CI) aunque sea un valor de prueba.
    const claveTipeada = 'claveSegura123'
    const { container } = render(<UserManagementContainer />)

    fireEvent.click(screen.getByRole('button', { name: /nuevo usuario/i }))
    const [email, nombre, apellido, telefono] = Array.from(
      container.querySelectorAll<HTMLInputElement>(
        'form:not([role="search"]) input:not([type="password"])'
      )
    )
    fireEvent.change(email!, { target: { value: 'luz@example.com' } })
    fireEvent.change(nombre!, { target: { value: 'Luz' } })
    fireEvent.change(apellido!, { target: { value: 'Paz' } })
    fireEvent.change(telefono!, { target: { value: '1155550102' } })
    fireEvent.change(container.querySelector('form input[type="password"]')!, {
      target: { value: claveTipeada }
    })
    fireEvent.click(screen.getByRole('button', { name: 'Crear Usuario' }))

    await waitFor(() => expect(mockCreate).toHaveBeenCalledTimes(1))
    expect(mockCreate).toHaveBeenCalledWith({
      email: 'luz@example.com',
      password: claveTipeada,
      firstName: 'Luz',
      lastName: 'Paz',
      phone: '1155550102',
      role: 'staff'
    })
  })

  it('eliminar pregunta con el dialogo propio y solo borra al confirmar (D1)', async () => {
    render(<UserManagementContainer />)

    fireEvent.click(screen.getByRole('button', { name: /eliminar/i }))
    fireEvent.click(
      within(
        screen.getByRole('alertdialog', { name: '¿Estás seguro de eliminar este usuario?' })
      ).getByRole('button', { name: 'Cancelar' })
    )
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(mockDelete).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: /eliminar/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar' }))

    await waitFor(() => expect(mockDelete).toHaveBeenCalledWith('usr-1'))
  })

  it('el admin de tienda no ve "Administrador" al crear; el superadmin si (FF-09)', () => {
    const { unmount } = render(<UserManagementContainer />)
    fireEvent.click(screen.getByRole('button', { name: /nuevo usuario/i }))
    expect(opcionesDeRol()).not.toContain('Administrador')
    unmount()

    mockViewer = { public_id: 'admin-1', is_global_admin: true }
    render(<UserManagementContainer />)
    fireEvent.click(screen.getByRole('button', { name: /nuevo usuario/i }))
    expect(opcionesDeRol()).toContain('Administrador')
  })

  it('editar a otro admin muestra su rol pero no deja cambiar rol, clave ni darlo de baja', () => {
    mockUsersQuery = { data: [otroAdmin], isLoading: false, error: null }
    const { container } = render(<UserManagementContainer />)

    expect(screen.queryByRole('button', { name: /eliminar/i })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /editar/i }))
    expect(opcionesDeRol()).toContain('Administrador')
    expect(screen.getByRole('combobox')).toBeDisabled()
    expect(container.querySelector('input[type="password"]')).toBeNull()
  })

  it('un 409 al crear muestra el texto neutro, no el del servidor', async () => {
    mockCreate.mockReset()
    mockCreate.mockRejectedValue(
      Object.assign(new Error('email ana@example.com ya existe'), {
        context: { errorCode: 'RESOURCE_CONFLICT' }
      })
    )
    render(<UserManagementContainer />)

    fireEvent.click(screen.getByRole('button', { name: /nuevo usuario/i }))
    fireEvent.submit(screen.getByRole('button', { name: 'Crear Usuario' }).closest('form')!)

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Ya existe una cuenta con ese email o teléfono.'
    )
  })

  it('si la baja falla lo avisa en vez de callarse', async () => {
    mockDelete.mockRejectedValue(
      Object.assign(new Error('403'), { context: { errorCode: 'PERMISSION_DENIED' } })
    )
    render(<UserManagementContainer />)

    fireEvent.click(screen.getByRole('button', { name: /eliminar/i }))
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar' }))

    expect(
      await screen.findByText(
        'Solo el soporte global puede cambiar el acceso de otro administrador.'
      )
    ).toBeInTheDocument()
  })

  it('busca en el servidor: q para nombre o telefono, email exacto si hay @', () => {
    render(<UserManagementContainer />)
    const buscador = screen.getByRole('searchbox', { name: 'Buscar usuario' })

    expect(mockListQuery).toHaveBeenLastCalledWith({ limit: 100, includeInactive: true })

    fireEvent.change(buscador, { target: { value: ' ana ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Buscar' }))
    expect(mockListQuery).toHaveBeenLastCalledWith({ limit: 100, includeInactive: true, q: 'ana' })

    fireEvent.change(buscador, { target: { value: 'Ana@Example.com ' } })
    fireEvent.submit(buscador.closest('form')!)
    expect(mockListQuery).toHaveBeenLastCalledWith({
      limit: 100,
      includeInactive: true,
      email: 'ana@example.com'
    })
  })

  // 2026-09-30 (F4-03): la lista de usuarios cortaba en 200 sin forma de ver
  // el resto; el aviso "Mostrando los primeros 200" era el unico camino.
  it('con mas paginas muestra "Ver más" y pide la siguiente', () => {
    mockUsersQuery = { data: [usuario], isLoading: false, error: null, hasNextPage: true }
    mockFetchNextPage.mockReset()
    render(<UserManagementContainer />)

    fireEvent.click(screen.getByRole('button', { name: 'Ver más' }))

    expect(mockFetchNextPage).toHaveBeenCalledTimes(1)
    expect(screen.queryByText(/Mostrando los primeros/)).not.toBeInTheDocument()
  })

  it('"Ver más" queda deshabilitado mientras llega la pagina siguiente', () => {
    mockUsersQuery = {
      data: [usuario],
      isLoading: false,
      error: null,
      hasNextPage: true,
      isFetchingNextPage: true
    }
    render(<UserManagementContainer />)

    expect(screen.getByRole('button', { name: /ver más|cargando/i })).toBeDisabled()
  })

  it('una pagina corta no muestra "Ver más"', () => {
    mockUsersQuery = { data: [usuario], isLoading: false, error: null, hasNextPage: false }
    render(<UserManagementContainer />)

    expect(screen.queryByRole('button', { name: /ver más/i })).not.toBeInTheDocument()
  })

  it('si falla la lista lo avisa en vez de mostrarla vacia (N2)', () => {
    mockUsersQuery = { data: undefined, isLoading: false, error: new Error('500') }
    render(<UserManagementContainer />)

    expect(screen.getByRole('alert')).toHaveTextContent('No se pudieron cargar los usuarios.')
  })
})
