import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import { Service } from '@domain/entities/Service'
import type { IServiceRepository } from '@domain/repositories/IServiceRepository'

import { ServiceService } from '@application/services/ServiceService'

import { ServiceFormModal } from './ServiceFormModal'

// ServiceService.ts arma su singleton con el apiClient real (runtime-env /
// import.meta, que ts-jest no compila): se mockea el cliente HTTP.
jest.mock('@infrastructure/http/client', () => ({
  __esModule: true,
  default: {}
}))

/**
 * El riesgo de F10-03 no es "falta un campo": es que el formulario de edicion
 * arranque en los defaults y guardar APAGUE una seña ya configurada, dejando
 * de cobrarle a la tienda. Toda la proteccion vive en el `useEffect` que carga
 * los valores reales, asi que es lo que se prueba aca: montando el componente,
 * no armando a mano el payload que el mapper despues copia.
 */
const servicioConSena = () =>
  Service.fromPrimitives({
    id: 'svc_1',
    name: 'Corte premium',
    description: 'Con lavado',
    duration_minutes: 45,
    price: 12000,
    color: '#3b82f6',
    image_url: null,
    youtube_trailer_url: null,
    is_active: true,
    deposit_mode: 'required',
    deposit_type: 'percent',
    deposit_amount: 50
  })

// La imagen no es lo que prueban los casos de sena: dobles que no se llaman.
const sinImagen = () => ({ onUploadImage: jest.fn(), onRemoveImage: jest.fn() })

const montoDeSena = () => screen.getByLabelText<HTMLInputElement>(/Porcentaje \(%\)|Monto fijo/)

describe('ServiceFormModal — politica de sena', () => {
  it('al editar, los controles arrancan con la sena REAL del servicio', () => {
    render(
      <ServiceFormModal
        isOpen
        onClose={jest.fn()}
        onSubmit={jest.fn()}
        editingService={servicioConSena()}
        {...sinImagen()}
      />
    )

    expect(screen.getByDisplayValue('Corte premium')).toBeInTheDocument()
    // Si esto diera 'none'/'percent'/vacio, guardar apagaria la sena.
    expect(screen.getByLabelText<HTMLSelectElement>(/Modo/i).value).toBe('required')
    expect(screen.getByLabelText<HTMLSelectElement>(/Tipo/i).value).toBe('percent')
    expect(montoDeSena().value).toBe('50')
  })

  it('cambiar solo el nombre manda la sena intacta', async () => {
    // El escenario exacto que la auditoria marca como riesgo: el dueño entra a
    // corregir el nombre y no toca la sena.
    const onSubmit = jest.fn().mockResolvedValue(undefined)
    render(
      <ServiceFormModal
        isOpen
        onClose={jest.fn()}
        onSubmit={onSubmit}
        editingService={servicioConSena()}
        {...sinImagen()}
      />
    )

    fireEvent.change(screen.getByDisplayValue('Corte premium'), {
      target: { value: 'Corte premium plus' }
    })
    fireEvent.click(screen.getByRole('button', { name: /Guardar/i }))

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1))
    expect(onSubmit.mock.calls[0]?.[0]).toMatchObject({
      name: 'Corte premium plus',
      depositMode: 'required',
      depositType: 'percent',
      depositAmount: 50
    })
  })

  it('un servicio nuevo arranca sin sena', () => {
    render(<ServiceFormModal isOpen onClose={jest.fn()} onSubmit={jest.fn()} {...sinImagen()} />)

    expect(screen.getByLabelText<HTMLSelectElement>(/Modo/i).value).toBe('none')
    // Con la sena apagada no se pide ni tipo ni monto.
    expect(screen.queryByLabelText(/Porcentaje \(%\)|Monto fijo/)).not.toBeInTheDocument()
  })
})

/**
 * D-20260930-09 (2026-10-01): el formulario rechaza lo que el backend
 * rechaza, al crear y al editar, y dice POR QUE. Antes el alta mostraba
 * "No se pudo guardar" (BaseService envuelve el ZodError en un Error plano) y
 * la edicion no validaba nada: un porcentaje de 150 viajaba y volvia 422.
 * Se arma con el ServiceService real sobre un repositorio doble: lo que se
 * prueba es el camino formulario -> servicio -> mensaje.
 */
describe('ServiceFormModal — motivo del rechazo (D-20260930-09)', () => {
  const repositorio = () =>
    ({
      findAll: jest.fn(),
      findById: jest.fn(),
      create: jest.fn().mockImplementation(async (created: Service) => created),
      update: jest.fn().mockImplementation(async () => servicioConSena()),
      delete: jest.fn(),
      uploadImage: jest.fn(),
      removeImage: jest.fn()
    }) as jest.Mocked<IServiceRepository>

  it('al crear con una descripcion de 1001 caracteres muestra ese motivo y no llama a la API', async () => {
    // 2026-10-01: el alta rechazaba en el cliente pero mostraba "No se pudo
    // guardar", sin decir que campo corregir.
    const repo = repositorio()
    const service = new ServiceService(repo)
    render(
      <ServiceFormModal
        isOpen
        onClose={jest.fn()}
        onSubmit={async (data) => {
          await service.createService(data)
        }}
        {...sinImagen()}
      />
    )

    fireEvent.change(screen.getByPlaceholderText('Ej: Corte de Cabello Premium'), {
      target: { value: 'Corte' }
    })
    fireEvent.change(screen.getByPlaceholderText('Describí qué incluye el servicio...'), {
      target: { value: 'a'.repeat(1001) }
    })
    fireEvent.click(screen.getByRole('button', { name: /Crear Servicio/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'La descripción no puede superar los 1000 caracteres'
    )
    expect(screen.queryByText('No se pudo guardar')).not.toBeInTheDocument()
    expect(repo.create).not.toHaveBeenCalled()
  })

  it('al editar con un porcentaje de 150 muestra el motivo y no llama a la API', async () => {
    // 2026-10-01: la edicion no validaba en el cliente; el PATCH con 150%
    // salia y el backend lo rechazaba ("un porcentaje de sena no puede
    // superar 100"), igual que la base (ck_services_deposit_percent_max).
    const repo = repositorio()
    const service = new ServiceService(repo)
    render(
      <ServiceFormModal
        isOpen
        onClose={jest.fn()}
        onSubmit={async (data) => {
          await service.updateService('svc_1', data)
        }}
        editingService={servicioConSena()}
        {...sinImagen()}
      />
    )

    fireEvent.change(montoDeSena(), { target: { value: '150' } })
    fireEvent.click(screen.getByRole('button', { name: /Guardar/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'El porcentaje de la seña no puede superar 100'
    )
    expect(repo.update).not.toHaveBeenCalled()
  })

  it('al editar con datos validos guarda igual', async () => {
    const repo = repositorio()
    const service = new ServiceService(repo)
    const onClose = jest.fn()
    render(
      <ServiceFormModal
        isOpen
        onClose={onClose}
        onSubmit={async (data) => {
          await service.updateService('svc_1', data)
        }}
        editingService={servicioConSena()}
        {...sinImagen()}
      />
    )

    fireEvent.change(screen.getByDisplayValue('Corte premium'), {
      target: { value: 'Renombrado' }
    })
    fireEvent.click(screen.getByRole('button', { name: /Guardar/i }))

    await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1))
    expect(repo.update).toHaveBeenCalledWith(
      'svc_1',
      expect.objectContaining({ name: 'Renombrado', depositType: 'percent', depositAmount: 50 })
    )
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

/**
 * 2026-09-30: el panel no podia subir la imagen de un servicio aunque el
 * backend ya lo permitia. La subida y la baja se guardan al instante; el riesgo
 * es que el formulario siga con la URL VIEJA y un Guardar posterior la mande:
 * el backend responde 422 o desvincula y borra la imagen recien subida
 * (modules/stores/media.py::resolve_image_link).
 */
describe('ServiceFormModal — imagen del servicio', () => {
  const URL_VIEJA = 'https://app.test/api/stores/media/vieja'
  const URL_NUEVA = 'https://app.test/api/stores/media/nueva'
  const PNG = [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 0]

  const conImagen = (imageUrl: string | null) =>
    Service.fromPrimitives({ ...servicioConSena().toPrimitives(), image_url: imageUrl })

  const montar = (
    opciones: {
      editingService?: Service | null
      onUploadImage?: jest.Mock
      readOnlyReason?: string
    } = {}
  ) => {
    const props = {
      onSubmit: jest.fn().mockResolvedValue(undefined),
      onUploadImage: opciones.onUploadImage ?? jest.fn().mockResolvedValue(conImagen(URL_NUEVA)),
      onRemoveImage: jest.fn().mockResolvedValue(conImagen(null)),
      readOnlyReason: opciones.readOnlyReason
    }
    const editingService =
      'editingService' in opciones ? opciones.editingService : conImagen(URL_VIEJA)
    render(
      <ServiceFormModal isOpen onClose={jest.fn()} editingService={editingService} {...props} />
    )
    return props
  }

  const elegir = (file: File) =>
    fireEvent.change(screen.getByLabelText(/Subir imagen/i), { target: { files: [file] } })

  const urlDelFormulario = () =>
    screen.getByPlaceholderText<HTMLInputElement>('https://.../servicio.jpg').value

  const png = () => new File([new Uint8Array(PNG)], 'foto.png', { type: 'image/png' })

  // 2026-10-02 (F4-15): la vista previa no tenia tamano ni carga diferida y
  // el modal saltaba al llegar la imagen.
  it('la vista previa reserva su caja de 48 px y carga diferida', () => {
    montar()

    const img = screen.getByRole('img', { name: 'Corte premium' })
    expect(img).toHaveAttribute('src', URL_VIEJA)
    expect(img).toHaveAttribute('loading', 'lazy')
    expect(img).toHaveAttribute('decoding', 'async')
    expect(img).toHaveAttribute('width', '48')
    expect(img).toHaveAttribute('height', '48')
  })

  it('en el alta no hay input de archivo y se explica por que', () => {
    montar({ editingService: null })

    expect(screen.queryByLabelText(/Subir imagen/i)).not.toBeInTheDocument()
    expect(screen.getByText(/Guardá el servicio para poder subir una imagen/)).toBeInTheDocument()
    // La URL externa sigue disponible en el alta.
    expect(screen.getByPlaceholderText('https://.../servicio.jpg')).toBeInTheDocument()
  })

  it('en la edicion hay un input de archivo solo para PNG, JPEG y WebP', () => {
    montar()

    const input = screen.getByLabelText(/Subir imagen/i)
    expect(input).toHaveAttribute('type', 'file')
    expect(input).toHaveAttribute('accept', 'image/png,image/jpeg,image/webp')
    expect(screen.getByText(/cerrar sin guardar no la deshace/i)).toBeInTheDocument()
  })

  it('una subida OK actualiza la URL y Guardar no manda la vieja', async () => {
    const props = montar()
    const archivo = png()

    elegir(archivo)

    await waitFor(() => expect(props.onUploadImage).toHaveBeenCalledWith('svc_1', archivo))
    await waitFor(() => expect(urlDelFormulario()).toBe(URL_NUEVA))
    fireEvent.click(screen.getByRole('button', { name: /Guardar/i }))

    await waitFor(() => expect(props.onSubmit).toHaveBeenCalledTimes(1))
    expect(props.onSubmit.mock.calls[0]?.[0]).toMatchObject({ imageUrl: URL_NUEVA })
  })

  it('un SVG se rechaza sin llamar a la API', async () => {
    const props = montar()

    elegir(new File(['<svg/>'], 'x.svg', { type: 'image/svg+xml' }))

    expect(
      await screen.findByText(/PNG, JPEG o WebP/, { selector: '[role="alert"]' })
    ).toBeInTheDocument()
    expect(props.onUploadImage).not.toHaveBeenCalled()
  })

  it('un archivo con magic bytes falsos se rechaza sin llamar a la API', async () => {
    const props = montar()

    elegir(new File(['no soy un png'], 'x.png', { type: 'image/png' }))

    expect(
      await screen.findByText(/no es una imagen/, { selector: '[role="alert"]' })
    ).toBeInTheDocument()
    expect(props.onUploadImage).not.toHaveBeenCalled()
  })

  it('un error de la API se muestra y la URL no cambia', async () => {
    const props = montar({ onUploadImage: jest.fn().mockRejectedValue(new Error('boom')) })

    elegir(png())

    expect(await screen.findByText('No se pudo subir la imagen')).toBeInTheDocument()
    expect(props.onUploadImage).toHaveBeenCalledTimes(1)
    expect(urlDelFormulario()).toBe(URL_VIEJA)
  })

  it('"Quitar imagen" la borra y Guardar no manda la vieja', async () => {
    const props = montar()

    fireEvent.click(screen.getByRole('button', { name: /Quitar imagen/i }))

    await waitFor(() => expect(props.onRemoveImage).toHaveBeenCalledWith('svc_1'))
    await waitFor(() => expect(urlDelFormulario()).toBe(''))
    fireEvent.click(screen.getByRole('button', { name: /Guardar/i }))

    await waitFor(() => expect(props.onSubmit).toHaveBeenCalledTimes(1))
    expect(props.onSubmit.mock.calls[0]?.[0]).toMatchObject({ imageUrl: '' })
  })

  // 2026-10-01: con la tienda suspendida cada accion fallaba con 402 en vez de
  // verse deshabilitada (FF-15). POST y DELETE /services/{id}/image y el PATCH
  // del guardado no estan en SUSPENSION_ALLOWED_WRITES.
  it('con la tienda suspendida subir, quitar y guardar quedan deshabilitados', () => {
    montar({ readOnlyReason: 'Tienda suspendida' })

    const input = screen.getByLabelText(/Subir imagen/i)
    expect(input).toBeDisabled()
    expect(input.closest('label')).toHaveAttribute('title', 'Tienda suspendida')
    for (const name of [/Quitar imagen/i, /Guardar/i]) {
      const button = screen.getByRole('button', { name })
      expect(button).toBeDisabled()
      expect(button).toHaveAttribute('title', 'Tienda suspendida')
    }
  })

  it('sin suspension subir, quitar y guardar siguen habilitados', () => {
    montar()

    expect(screen.getByLabelText(/Subir imagen/i)).not.toBeDisabled()
    expect(screen.getByRole('button', { name: /Quitar imagen/i })).not.toBeDisabled()
    expect(screen.getByRole('button', { name: /Guardar/i })).not.toBeDisabled()
  })
})
