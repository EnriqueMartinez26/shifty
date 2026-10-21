import type { ComponentProps } from 'react'

import { fireEvent, render, screen } from '@testing-library/react'

import { SettingsIdentityTab } from './SettingsIdentityTab'
import { getBusinessLabels } from '../../../lib/businessLabels'

// 2026-10-02: la pestana de identidad salio de Settings.tsx (F11b-08). Cada
// campo devuelve solo su clave; subir el logo lo valida la pagina (regla 19).

jest.mock('@presentation/hooks/useManagedServices', () => ({
  useManagedServices: () => ({ data: [] })
}))

type TabProps = ComponentProps<typeof SettingsIdentityTab>

const value: TabProps['value'] = {
  business_type: 'generic',
  name: 'Peluqueria Tucuman',
  slug: 'peluqueria-tucuman',
  logo_url: '',
  primary_color: '#ff6600',
  cover_url: '',
  cover_position: null,
  whatsapp_number: '',
  description: '',
  custom_client_fields: [],
  instagram_url: '',
  facebook_url: '',
  website_url: ''
}

const renderTab = (overrides: Partial<TabProps> = {}) => {
  const props: TabProps = {
    value,
    labels: getBusinessLabels('generic'),
    slugError: undefined,
    logoError: null,
    uploadingLogo: false,
    coverError: null,
    uploadingCover: false,
    onChange: jest.fn(),
    onLogoUpload: jest.fn(),
    onCoverUpload: jest.fn(),
    ...overrides
  }
  const view = render(<SettingsIdentityTab {...props} />)
  return { props, ...view }
}

describe('SettingsIdentityTab', () => {
  it('el nombre devuelve solo su campo', () => {
    const { props } = renderTab()

    fireEvent.change(screen.getByDisplayValue('Peluqueria Tucuman'), {
      target: { value: 'Otro nombre' }
    })

    expect(props.onChange).toHaveBeenCalledWith({ name: 'Otro nombre' })
  })

  it('el slug se normaliza antes de devolverlo y muestra su error', () => {
    const { props } = renderTab({ slugError: 'Ese enlace ya lo usa otro negocio. Elegí otro.' })

    const slug = screen.getByLabelText('Slug de la URL')
    expect(slug).toHaveAttribute('aria-invalid', 'true')
    expect(screen.getByText('Ese enlace ya lo usa otro negocio. Elegí otro.')).toBeInTheDocument()
    fireEvent.change(slug, { target: { value: 'Mi Local' } })

    expect(props.onChange).toHaveBeenCalledWith({ slug: 'mi-local' })
  })

  it('agregar un campo extra devuelve custom_client_fields', () => {
    const { props } = renderTab()

    fireEvent.click(screen.getByRole('button', { name: 'Agregar campo' }))

    expect(props.onChange).toHaveBeenCalledWith({
      custom_client_fields: [expect.objectContaining({ key: 'campo_1' })]
    })
  })

  it('elegir un archivo delega en onLogoUpload y el error se muestra', () => {
    const { props } = renderTab({ logoError: 'La imagen supera el máximo de 1 MB.' })
    const input = screen.getByLabelText('Subir logo')
    expect(input).toHaveAttribute('type', 'file')
    expect(input).toHaveAttribute('accept', 'image/png,image/jpeg,image/webp')

    fireEvent.change(input, {
      target: { files: [new File(['x'], 'logo.png', { type: 'image/png' })] }
    })

    expect(props.onLogoUpload).toHaveBeenCalledTimes(1)
    expect(props.onCoverUpload).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('La imagen supera el máximo de 1 MB.')
  })

  // 2026-10-21 (S2b): la CSP de produccion (img-src 'self' data: blob:) no
  // carga imagenes de otro sitio; el logo y la portada solo se suben.
  it('no hay campos para pegar la URL del logo ni de la portada', () => {
    renderTab()

    expect(screen.queryByPlaceholderText('…o pegá una URL https://')).not.toBeInTheDocument()
    expect(screen.queryByText('URL de portada')).not.toBeInTheDocument()
    // El unico "https://..." que queda es el del sitio web.
    expect(screen.getAllByPlaceholderText('https://...')).toHaveLength(1)
  })

  it('la portada se sube con su boton, sus limites y su error', () => {
    const { props } = renderTab({ coverError: 'La imagen supera el máximo de 2 MB.' })
    const input = screen.getByLabelText('Subir portada')
    expect(input).toHaveAttribute('type', 'file')
    expect(input).toHaveAttribute('accept', 'image/png,image/jpeg,image/webp')
    expect(
      screen.getByText('PNG, JPEG o WebP · máx 2 MB · recomendado 1500 × 500')
    ).toBeInTheDocument()

    fireEvent.change(input, {
      target: { files: [new File(['x'], 'portada.webp', { type: 'image/webp' })] }
    })

    expect(props.onCoverUpload).toHaveBeenCalledTimes(1)
    expect(props.onLogoUpload).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('La imagen supera el máximo de 2 MB.')
  })

  it('la vista previa muestra la portada subida, ancha y sin estirarse', () => {
    renderTab({ value: { ...value, cover_url: '/media/cover.webp' } })

    const img = screen.getByRole('img', { name: 'Portada' })
    expect(img).toHaveAttribute('src', '/media/cover.webp')
    expect(img).toHaveClass('object-cover')
    expect(img.parentElement).toHaveClass('aspect-[3/1]')
  })

  // 2026-10-22 (S10.1): con la foto real el portal mostraba el medio y cortaba
  // lo que importaba. La tienda elige que parte se ve.
  describe('encuadre de la portada', () => {
    const conPortada = { ...value, cover_url: '/media/cover.webp' }

    it('sin portada no ofrece elegir el encuadre', () => {
      renderTab()

      expect(
        screen.queryByRole('radiogroup', { name: 'Qué parte de la foto se ve' })
      ).not.toBeInTheDocument()
    })

    it('con portada ofrece Arriba, Centro y Abajo, de 44 px, sin ninguno elegido', () => {
      renderTab({ value: conPortada })

      const grupo = screen.getByRole('radiogroup', { name: 'Qué parte de la foto se ve' })
      const opciones = ['Arriba', 'Centro', 'Abajo'].map((nombre) =>
        screen.getByRole('radio', { name: nombre })
      )
      opciones.forEach((opcion) => {
        expect(grupo.contains(opcion)).toBe(true)
        expect((opcion as HTMLInputElement).checked).toBe(false)
        expect(opcion.closest('label')).toHaveClass('min-h-11', 'min-w-11')
      })
      // Sin elegir, la vista previa encuadra como el portal.
      expect(screen.getByRole('img', { name: 'Portada' }).style.objectPosition).toBe('center 65%')
    })

    it('marca el encuadre guardado y la vista previa lo sigue', () => {
      renderTab({ value: { ...conPortada, cover_position: 'top' } })

      expect((screen.getByRole('radio', { name: 'Arriba' }) as HTMLInputElement).checked).toBe(true)
      expect(screen.getByRole('img', { name: 'Portada' }).style.objectPosition).toBe('center 20%')
    })

    it('elegir otro devuelve solo cover_position', () => {
      const { props } = renderTab({ value: conPortada })

      fireEvent.click(screen.getByRole('radio', { name: 'Abajo' }))

      expect(props.onChange).toHaveBeenCalledWith({ cover_position: 'bottom' })
    })
  })

  it('subiendo la portada se apaga solo su boton', () => {
    renderTab({ uploadingCover: true })

    expect(screen.getByLabelText('Subiendo...')).toBeDisabled()
    expect(screen.getByLabelText('Subir logo')).not.toBeDisabled()
  })

  // 2026-10-02 (F4-15): el logo no tenia tamano ni carga diferida y la
  // pestana saltaba al llegar la imagen.
  it('el logo reserva su caja de 80 px y carga diferida', () => {
    renderTab({ value: { ...value, logo_url: 'https://cdn.test/logo.png' } })

    const img = screen.getByRole('img', { name: 'Logo' })
    expect(img).toHaveAttribute('loading', 'lazy')
    expect(img).toHaveAttribute('decoding', 'async')
    expect(img).toHaveAttribute('width', '80')
    expect(img).toHaveAttribute('height', '80')
  })

  it('subiendo o en solo lectura el input del logo se apaga', () => {
    const { unmount } = renderTab({ uploadingLogo: true })
    expect(screen.getByLabelText('Subiendo...')).toBeDisabled()
    expect(screen.getByLabelText('Subir portada')).not.toBeDisabled()
    unmount()

    renderTab({ readOnlyReason: 'Tienda suspendida' })
    for (const name of ['Subir logo', 'Subir portada']) {
      const input = screen.getByLabelText(name)
      expect(input).toBeDisabled()
      expect(input.closest('label')).toHaveAttribute('title', 'Tienda suspendida')
    }
  })

  // QA movil 2026-10-08: el prefijo decia /booking/ y los links reales son
  // /b/; la pestana medía hasta 887 px de ancho en 390 y tapaba "Copiar".
  it('el prefijo del slug es el de los links que se comparten', () => {
    renderTab()
    expect(screen.getByText('/b/')).toBeInTheDocument()
    expect(screen.queryByText('/booking/')).not.toBeInTheDocument()
  })

  it('ninguna columna se estira con su contenido', () => {
    const { container } = renderTab()
    const columns = container.querySelectorAll(':scope > div > .grid > *')
    expect(columns.length).toBeGreaterThan(0)
    for (const column of columns) expect(column.classList.contains('min-w-0')).toBe(true)
    expect(
      screen.getByRole('textbox', { name: 'Slug de la URL' }).classList.contains('min-w-0')
    ).toBe(true)
  })
})
