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
    onChange: jest.fn(),
    onLogoUpload: jest.fn(),
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
    const { props, container } = renderTab({ logoError: 'La imagen supera el máximo de 1 MB.' })
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')
    if (!input) throw new Error('Falta el input del logo')

    fireEvent.change(input, {
      target: { files: [new File(['x'], 'logo.png', { type: 'image/png' })] }
    })

    expect(props.onLogoUpload).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('alert')).toHaveTextContent('La imagen supera el máximo de 1 MB.')
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
    const { container, unmount } = renderTab({ uploadingLogo: true })
    expect(screen.getByText('Subiendo...')).toBeInTheDocument()
    expect(container.querySelector('input[type="file"]')).toBeDisabled()
    unmount()

    const readOnly = renderTab({ readOnlyReason: 'Tienda suspendida' })
    const input = readOnly.container.querySelector('input[type="file"]')
    expect(input).toBeDisabled()
    expect(input?.closest('label')).toHaveAttribute('title', 'Tienda suspendida')
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
